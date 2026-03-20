#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
从强制测光数据中提取 Last Non-Detection

功能：
1. 从 merged/*.csv 光变曲线中识别 non-detection (SNR < 3)
2. 找到第一个 detection 之前的最后一个 non-detection
3. 严谨确认：确保这个 non-detection 之后没有其他 non-detection（直到第一个 detection）

输出：
- last_nondet_phase_forced: 强制测光中的 last non-detection phase
- last_nondet_mjd_forced: 强制测光中的 last non-detection MJD
- last_nondet_band_forced: 对应的波段
- last_nondet_limiting_flux_forced: 对应的探测极限 (3σ flux)
- forced_nondet_is_clean: 是否为"干净"的 last non-detection（之后无其他 non-det）
"""

import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional, Dict, Any

# 路径配置
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / 'data'
MERGED_DIR = DATA_DIR / 'merged'

# SNR 阈值
SNR_DETECTION_THRESHOLD = 3.0  # SNR >= 3 为 detection
SNR_NONDET_THRESHOLD = 3.0     # SNR < 3 为 non-detection

# 波段典型探测极限 (3σ, µJy)
# 用于计算等效 limiting magnitude
BAND_3SIGMA_FLUX = {
    'ZTF_g': 12.0,    # ~20.8 mag
    'ZTF_r': 15.0,    # ~20.5 mag
    'ZTF_i': 25.0,    # ~20.0 mag
    'ATLAS_o': 50.0,  # ~19.5 mag
    'ATLAS_c': 35.0,  # ~19.7 mag
}

# flux (µJy) 转 AB mag
def flux_to_mag(flux_ujy: float) -> float:
    """Convert flux (µJy) to AB magnitude"""
    if flux_ujy <= 0:
        return 99.0
    return 23.9 - 2.5 * np.log10(flux_ujy)


def mag_to_flux(mag: float) -> float:
    """Convert AB magnitude to flux (µJy)"""
    return 10 ** ((23.9 - mag) / 2.5)


def extract_forced_last_nondet(
    merged_csv_path: Path,
    discovery_mjd: Optional[float] = None,
    phase_min: float = -30,
    phase_max: float = 0,  # 改为0，只看发现之前的数据，避免信息泄露
) -> Dict[str, Any]:
    """
    从合并的强制测光数据中提取 last non-detection
    
    重要：为避免信息泄露，只使用 phase < 0（发现日期之前）的数据
    
    Args:
        merged_csv_path: merged/*.csv 文件路径
        discovery_mjd: 发现日期 MJD（如果 None，从文件中读取）
        phase_min: 搜索的最小 phase
        phase_max: 搜索的最大 phase，默认为0（发现日期）
    
    Returns:
        dict: 包含 last non-detection 信息的字典
    """
    result = {
        'has_forced_nondet': False,
        'last_nondet_phase_forced': None,
        'last_nondet_mjd_forced': None,
        'last_nondet_band_forced': None,
        'last_nondet_limiting_flux_forced': None,
        'last_nondet_limiting_mag_forced': None,
        'forced_nondet_is_clean': False,
        'first_det_phase_forced': None,
        'gap_nondet_to_det_forced': None,
        'n_nondet_before_det_forced': 0,
    }
    
    if not merged_csv_path.exists():
        return result
    
    try:
        df = pd.read_csv(merged_csv_path, comment='#')
    except Exception:
        return result
    
    if df.empty or 'phase' not in df.columns:
        return result
    
    # 确保必要的列存在
    required_cols = ['phase', 'flux_ujy', 'flux_error_ujy', 'band']
    if not all(col in df.columns for col in required_cols):
        return result
    
    # 过滤有效数据
    df = df.dropna(subset=['phase', 'flux_ujy', 'flux_error_ujy'])
    df = df[df['flux_error_ujy'] > 0]
    
    # 限制 phase 范围：只使用发现之前的数据 (phase < phase_max)
    # 这是防止信息泄露的关键！
    df = df[(df['phase'] >= phase_min) & (df['phase'] < phase_max)]
    
    if df.empty:
        return result
    
    # 计算 SNR
    df = df.copy()
    df['snr'] = np.abs(df['flux_ujy']) / df['flux_error_ujy']
    df['is_detection'] = df['snr'] >= SNR_DETECTION_THRESHOLD
    
    # 按 phase 排序
    df = df.sort_values('phase')
    
    # 在发现之前的数据中，找第一个 detection
    detections = df[df['is_detection']]
    
    # 如果发现前没有detection，使用phase_max（发现日期）作为first_det
    if detections.empty:
        first_det_phase = phase_max  # 使用发现日期作为参考点
        first_det_mjd = None
    else:
        first_det_phase = detections['phase'].iloc[0]
        first_det_mjd = detections['mjd'].iloc[0] if 'mjd' in detections.columns else None
    
    result['first_det_phase_forced'] = first_det_phase
    
    # 找第一个 detection 之前的所有 non-detection
    non_detections = df[(~df['is_detection']) & (df['phase'] < first_det_phase)]
    
    if non_detections.empty:
        return result
    
    # 取最后一个 non-detection（phase 最大的）
    last_nondet = non_detections.iloc[-1]
    last_nondet_phase = last_nondet['phase']
    last_nondet_mjd = last_nondet['mjd'] if 'mjd' in non_detections.columns else None
    last_nondet_band = last_nondet['band']
    last_nondet_flux_err = last_nondet['flux_error_ujy']
    
    # 计算 3σ limiting flux 和对应的 limiting magnitude
    limiting_flux_3sigma = 3.0 * last_nondet_flux_err
    limiting_mag = flux_to_mag(limiting_flux_3sigma)
    
    # 检查是否为"干净"的 last non-detection
    # 标准：在 last_nondet 之后、first_det 之前，没有其他 non-detection
    # 这意味着 last_nondet 是真正的"最后"一个非探测
    between = df[(df['phase'] > last_nondet_phase) & (df['phase'] < first_det_phase)]
    non_det_between = between[~between['is_detection']]
    is_clean = len(non_det_between) == 0
    
    # 如果不干净，找最"可靠"的 last non-detection
    # 可靠性标准：1. 之后没有其他 non-det 2. 距离 first_det 最近
    if not is_clean:
        # 从后往前找，找到第一个满足"之后无 non-det"的
        for i in range(len(non_detections) - 1, -1, -1):
            candidate = non_detections.iloc[i]
            candidate_phase = candidate['phase']
            
            # 检查 candidate 之后是否有其他 non-det
            after_candidate = df[(df['phase'] > candidate_phase) & (df['phase'] < first_det_phase)]
            non_det_after = after_candidate[~after_candidate['is_detection']]
            
            if len(non_det_after) == 0:
                # 这个 candidate 是干净的
                last_nondet = candidate
                last_nondet_phase = candidate['phase']
                last_nondet_mjd = candidate['mjd'] if 'mjd' in df.columns else None
                last_nondet_band = candidate['band']
                last_nondet_flux_err = candidate['flux_error_ujy']
                limiting_flux_3sigma = 3.0 * last_nondet_flux_err
                limiting_mag = flux_to_mag(limiting_flux_3sigma)
                is_clean = True
                break
    
    # 计算 gap
    gap = first_det_phase - last_nondet_phase
    
    # 填充结果
    result['has_forced_nondet'] = True
    result['last_nondet_phase_forced'] = float(last_nondet_phase)
    result['last_nondet_mjd_forced'] = float(last_nondet_mjd) if last_nondet_mjd is not None else None
    result['last_nondet_band_forced'] = str(last_nondet_band)
    result['last_nondet_limiting_flux_forced'] = float(limiting_flux_3sigma)
    result['last_nondet_limiting_mag_forced'] = float(limiting_mag)
    result['forced_nondet_is_clean'] = is_clean
    result['gap_nondet_to_det_forced'] = float(gap)
    result['n_nondet_before_det_forced'] = len(non_detections)
    
    return result


def extract_forced_nondet_per_band(
    merged_csv_path: Path,
    phase_min: float = -30,
    phase_max: float = 0,  # 改为0，只看发现之前的数据，避免信息泄露
) -> Dict[str, Dict[str, Any]]:
    """
    分波段提取 last non-detection
    
    重要：为避免信息泄露，只使用 phase < 0（发现日期之前）的数据
    
    NOTE: 如果某波段没有detection，则使用 phase_max（发现日期）来计算约束
    
    Returns:
        dict: {band: nondet_info}
    """
    result = {}
    
    if not merged_csv_path.exists():
        return result
    
    try:
        df = pd.read_csv(merged_csv_path, comment='#')
    except Exception:
        return result
    
    if df.empty or 'phase' not in df.columns:
        return result
    
    required_cols = ['phase', 'flux_ujy', 'flux_error_ujy', 'band']
    if not all(col in df.columns for col in required_cols):
        return result
    
    df = df.dropna(subset=['phase', 'flux_ujy', 'flux_error_ujy'])
    df = df[df['flux_error_ujy'] > 0]
    # 只使用发现之前的数据 (phase < phase_max)，避免信息泄露
    df = df[(df['phase'] >= phase_min) & (df['phase'] < phase_max)]
    
    if df.empty:
        return result
    
    df = df.copy()
    df['snr'] = np.abs(df['flux_ujy']) / df['flux_error_ujy']
    df['is_detection'] = df['snr'] >= SNR_DETECTION_THRESHOLD
    
    # 计算全局的 first detection phase（用于没有detection的波段）
    # 如果发现前没有detection，使用phase_max（发现日期）作为参考点
    all_detections = df[df['is_detection']]
    global_first_det_phase = all_detections['phase'].min() if not all_detections.empty else phase_max
    
    for band in df['band'].unique():
        band_df = df[df['band'] == band].sort_values('phase')
        
        band_detections = band_df[band_df['is_detection']]
        
        # 确定 first_det_phase：优先使用波段内的，否则使用全局的
        if not band_detections.empty:
            first_det_phase = band_detections['phase'].iloc[0]
        else:
            # 波段内无detection，使用全局first_det_phase（可能是phase_max）
            first_det_phase = global_first_det_phase
        
        non_detections = band_df[(~band_df['is_detection']) & (band_df['phase'] < first_det_phase)]
        
        if non_detections.empty:
            result[band] = {
                'has_nondet': False,
                'last_nondet_phase': None,
                'first_det_phase': float(first_det_phase),
                'gap': None,
            }
            continue
        
        last_nondet = non_detections.iloc[-1]
        gap = first_det_phase - last_nondet['phase']
        
        result[band] = {
            'has_nondet': True,
            'last_nondet_phase': float(last_nondet['phase']),
            'last_nondet_mjd': float(last_nondet['mjd']) if 'mjd' in last_nondet else None,
            'limiting_flux_3sigma': float(3.0 * last_nondet['flux_error_ujy']),
            'limiting_mag': float(flux_to_mag(3.0 * last_nondet['flux_error_ujy'])),
            'first_det_phase': float(first_det_phase),
            'gap': float(gap),
        }
    
    return result


def get_best_forced_constraint(per_band_info: Dict[str, Dict]) -> Dict[str, Any]:
    """
    从分波段信息中选择最佳约束
    
    选择标准：
    1. gap 最小（约束最紧）
    2. 相同 gap 时，选 limiting_mag 更深的
    """
    best = {
        'best_forced_constraint_band': None,
        'best_forced_constraint_phase': None,
        'best_forced_constraint_gap': None,
        'best_forced_constraint_lim_mag': None,
    }
    
    best_score = -999
    
    for band, info in per_band_info.items():
        if not info.get('has_nondet'):
            continue
        
        gap = info.get('gap', 999)
        lim_mag = info.get('limiting_mag', 19.0)
        
        # 评分：gap 越小越好（负相关），lim_mag 越深越好（正相关）
        # score = -gap + 0.3 * (lim_mag - 19)
        score = -gap + 0.3 * (lim_mag - 19.0)
        
        if score > best_score:
            best_score = score
            best['best_forced_constraint_band'] = band
            best['best_forced_constraint_phase'] = info.get('last_nondet_phase')
            best['best_forced_constraint_gap'] = gap
            best['best_forced_constraint_lim_mag'] = lim_mag
    
    return best


# ============================================================================
# 主函数：用于测试
# ============================================================================
def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Extract forced photometry last non-detection')
    parser.add_argument('--source', type=str, help='Source name (e.g., SN2018acj)')
    parser.add_argument('--all', action='store_true', help='Process all sources')
    args = parser.parse_args()
    
    if args.source:
        # 单个源
        csv_path = MERGED_DIR / f"{args.source}.csv"
        if not csv_path.exists():
            csv_path = MERGED_DIR / f"SN{args.source.replace('SN', '')}.csv"
        
        if csv_path.exists():
            result = extract_forced_last_nondet(csv_path)
            print(f"\n{args.source}:")
            for k, v in result.items():
                print(f"  {k}: {v}")
            
            per_band = extract_forced_nondet_per_band(csv_path)
            print(f"\n  Per-band:")
            for band, info in per_band.items():
                print(f"    {band}: {info}")
            
            best = get_best_forced_constraint(per_band)
            print(f"\n  Best constraint: {best}")
        else:
            print(f"File not found: {csv_path}")
    
    elif args.all:
        # 所有源
        stats = {'has_forced_nondet': 0, 'is_clean': 0, 'total': 0}
        
        for csv_path in MERGED_DIR.glob("SN*.csv"):
            result = extract_forced_last_nondet(csv_path)
            stats['total'] += 1
            if result['has_forced_nondet']:
                stats['has_forced_nondet'] += 1
            if result['forced_nondet_is_clean']:
                stats['is_clean'] += 1
        
        print(f"\n统计:")
        print(f"  总源数: {stats['total']}")
        print(f"  有强制测光 non-det: {stats['has_forced_nondet']} ({stats['has_forced_nondet']/stats['total']*100:.1f}%)")
        print(f"  干净的 non-det: {stats['is_clean']} ({stats['is_clean']/stats['total']*100:.1f}%)")
    
    else:
        # 示例
        sample_files = list(MERGED_DIR.glob("SN*.csv"))[:5]
        for csv_path in sample_files:
            result = extract_forced_last_nondet(csv_path)
            print(f"\n{csv_path.stem}:")
            print(f"  has_forced_nondet: {result['has_forced_nondet']}")
            print(f"  last_nondet_phase: {result['last_nondet_phase_forced']}")
            print(f"  is_clean: {result['forced_nondet_is_clean']}")
            print(f"  gap: {result['gap_nondet_to_det_forced']}")


if __name__ == "__main__":
    main()
