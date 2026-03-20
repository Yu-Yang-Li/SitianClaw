#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Step 2: Build Dynamic Samples from TNS Report Times
=====================================================

Simulate real-time discovery by progressively revealing observations
based on their TNS report times.

Usage:
    python step2_build_samples.py

Input:
    data/sources.csv                    (texp labels from Step 1)
    data/tns/parsed/tns_full_info.json  (TNS AT reports & LC summaries)
    data/merged_ned_info.csv            (NED host galaxy info, optional)

Output:
    data/dynamic_samples.pkl            (samples for training)
"""

import numpy as np
import pandas as pd
import json
import re
import pickle
import argparse
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from scipy import stats as scipy_stats
from astropy.coordinates import SkyCoord
import astropy.units as u
import warnings
warnings.filterwarnings('ignore')

# Import from local utils
from utils import get_filter_info, get_filter_color, safe_float

# Import forced photometry non-detection extractor (only per-band version needed)
from extract_forced_nondet import extract_forced_nondet_per_band

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / 'data'
RESULTS_DIR = BASE_DIR / 'results'

# Filter physics
FILTER_PHYSICS = {
    'r-ZTF': {'lambda_c': 642, 'survey': 'ZTF'},
    'g-ZTF': {'lambda_c': 472, 'survey': 'ZTF'},
    'i-ZTF': {'lambda_c': 783, 'survey': 'ZTF'},
    'orange-ATLAS': {'lambda_c': 679, 'survey': 'ATLAS'},
    'cyan-ATLAS': {'lambda_c': 533, 'survey': 'ATLAS'},
    'G-Gaia': {'lambda_c': 673, 'survey': 'GaiaAlerts'},
    'w-P1': {'lambda_c': 620, 'survey': 'Pan-STARRS'},
    'i-P1': {'lambda_c': 753, 'survey': 'Pan-STARRS'},
    'Unknown': {'lambda_c': 600, 'survey': 'Unknown'},
}


def parse_source_coords_from_merged(merged_csv):
    """Parse RA/Dec from merged CSV header comments."""
    ra = None
    dec = None
    if not merged_csv.exists():
        return ra, dec

    try:
        with open(merged_csv, 'r', encoding='utf-8', errors='ignore') as f:
            for _ in range(8):
                line = f.readline()
                if not line:
                    break
                line = line.strip()
                if line.startswith('# ra:'):
                    try:
                        ra = float(line.split(':', 1)[1].strip())
                    except (ValueError, TypeError):
                        ra = None
                elif line.startswith('# dec:'):
                    try:
                        dec = float(line.split(':', 1)[1].strip())
                    except (ValueError, TypeError):
                        dec = None
                if ra is not None and dec is not None:
                    break
    except Exception:
        return None, None

    return ra, dec


def compute_galactic_b(ra_deg, dec_deg):
    """Compute galactic latitude b (deg) from ICRS coordinates."""
    try:
        c = SkyCoord(ra=float(ra_deg) * u.deg, dec=float(dec_deg) * u.deg, frame='icrs')
        return float(c.galactic.b.deg)
    except Exception:
        return np.nan


def query_mw_ebv_irsa(ra_deg, dec_deg, timeout=20, retries=3):
    """Query IRSA dust service for Schlegel & Finkbeiner E(B-V)."""
    loc = urllib.parse.quote(f"{float(ra_deg):.7f} {float(dec_deg):.7f}")
    url = f"https://irsa.ipac.caltech.edu/cgi-bin/DUST/nph-dust?locstr={loc}"
    headers = {"User-Agent": "sn-clock/1.0 (feature-engineering)"}

    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            xml = urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8', 'ignore')
            m = re.search(r"<meanValueSandF>\s*([0-9.]+)\s*\(mag\)", xml, flags=re.S)
            if m:
                return float(m.group(1))
            m2 = re.search(r"<meanValueSFD>\s*([0-9.]+)\s*\(mag\)", xml, flags=re.S)
            if m2:
                return float(m2.group(1))
        except Exception:
            if i < retries - 1:
                time.sleep(0.6 * (i + 1))
            continue
    return np.nan


def build_sky_feature_cache(source_names, merged_dir, max_workers=8):
    """Build per-source sky feature cache: RA, Dec, galactic_b, mw_ebv."""
    cache_file = DATA_DIR / 'mw_ebv_cache.json'
    cache = {}
    if cache_file.exists():
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    def _needs_refresh(v):
        if not isinstance(v, dict):
            return True
        ebv = v.get('mw_ebv', np.nan)
        return pd.isna(ebv)

    missing = []
    for source_name in source_names:
        merged_csv = merged_dir / f"{source_name}.csv"
        cached = cache.get(source_name)
        if cached and not _needs_refresh(cached):
            continue

        ra = cached.get('ra') if isinstance(cached, dict) else None
        dec = cached.get('dec') if isinstance(cached, dict) else None
        if ra is None or dec is None:
            ra, dec = parse_source_coords_from_merged(merged_csv)
        if ra is None or dec is None:
            cache[source_name] = {'ra': None, 'dec': None, 'galactic_b': np.nan, 'mw_ebv': np.nan}
        else:
            missing.append((source_name, ra, dec))

    if missing:
        print(f"  Building sky feature cache for {len(missing)} sources (IRSA E(B-V))...")

        def _worker(item):
            src, ra, dec = item
            b = compute_galactic_b(ra, dec)
            ebv = query_mw_ebv_irsa(ra, dec)
            return src, {'ra': ra, 'dec': dec, 'galactic_b': b, 'mw_ebv': ebv}

        done = 0
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(_worker, it) for it in missing]
            for fut in as_completed(futures):
                src, info = fut.result()
                cache[src] = info
                done += 1
                if done % 100 == 0 or done == len(missing):
                    print(f"    IRSA queried: {done}/{len(missing)}")

        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
            print(f"  Saved sky cache: {cache_file}")
        except Exception:
            print("  Warning: failed to save mw_ebv cache")

    return cache


def parse_nondet_from_html(html_str, discovery_mjd):
    """Parse non-detection from LC HTML, including limiting magnitude"""
    if '[Last non detection]' not in str(html_str):
        return None

    nondet_pos = html_str.find('[Last non detection]')
    before_text = html_str[:nondet_pos]

    filter_name = 'Unknown'
    survey = 'Unknown'
    limiting_mag = None
    nondet_jd = None

    # 方法1: 找 "数字串ABMag" 模式，智能分割 JD 和 Mag
    # JD 格式: 245XXXX.XXX (2458000-2460000 范围)
    # Mag 格式: 14-24 范围
    num_abmag_match = re.search(r'([\d.]+)(ABMag|VegaMag)', before_text)
    if num_abmag_match:
        num_str = num_abmag_match.group(1)
        # 尝试不同的分割点，找到有效的 JD + Mag 组合
        for i in range(7, len(num_str)):
            possible_jd_str = num_str[:i]
            possible_mag_str = num_str[i:]
            if possible_jd_str and possible_mag_str:
                try:
                    jd = float(possible_jd_str)
                    mag = float(possible_mag_str)
                    if 2458000 < jd < 2460000 and 14 < mag < 24:
                        nondet_jd = jd
                        limiting_mag = mag
                        break
                except ValueError:
                    pass

    # 方法2: Fallback - 直接搜索 JD 模式（如果方法1失败）
    if nondet_jd is None:
        jd_pattern = r'(245\d{4}\.?\d{0,7})'
        jds = re.findall(jd_pattern, before_text)
        if jds:
            nondet_jd = float(jds[-1])

    if nondet_jd is None:
        return None

    nondet_mjd = nondet_jd - 2400000.5
    nondet_phase = nondet_mjd - discovery_mjd

    # 提取 filter 和 survey
    filter_patterns = [
        (r'r-ZTF', 'r-ZTF', 'ZTF'),
        (r'g-ZTF', 'g-ZTF', 'ZTF'),
        (r'i-ZTF', 'i-ZTF', 'ZTF'),
        (r'orange-ATLAS', 'orange-ATLAS', 'ATLAS'),
        (r'cyan-ATLAS', 'cyan-ATLAS', 'ATLAS'),
        (r'G-Gaia', 'G-Gaia', 'GaiaAlerts'),
        (r'w-P1', 'w-P1', 'Pan-STARRS'),
        (r'i-P1', 'i-P1', 'Pan-STARRS'),
        (r'g-Sloan', 'g-Sloan', 'ASASSN'),
        (r'V-crts', 'V-crts', 'CRTS'),
        (r'Clear-', 'Clear', 'Other'),
    ]

    for pattern, filt, surv in filter_patterns:
        if pattern in before_text:
            filter_name = filt
            survey = surv
            break

    return {
        'mjd': nondet_mjd,
        'phase': nondet_phase,
        'filter': filter_name,
        'survey': survey,
        'limiting_mag': limiting_mag,  # 实际的探测极限星等
    }


def extract_full_observations(tns_info):
    """Extract complete observation sequence from TNS info"""
    discovery_mjd = tns_info.get('discovery_mjd', 0)
    observations = []

    at_reports = list(tns_info.get('at_reports', []))

    # Build survey -> report_time mapping
    survey_report_times = {}
    for at in at_reports:
        survey = at.get('reporting_group') or at.get('data_source', 'Unknown')
        report_mjd = at.get('time_received_mjd')
        if survey and report_mjd:
            if survey not in survey_report_times:
                survey_report_times[survey] = report_mjd
            else:
                survey_report_times[survey] = min(survey_report_times[survey], report_mjd)

    # 1. AT Reports (detections)
    for at in at_reports:
        obs_mjd = at.get('discovery_mjd')
        report_mjd = at.get('time_received_mjd')
        if not obs_mjd or not report_mjd:
            continue

        filt = at.get('filter', 'Unknown')
        survey = at.get('reporting_group') or at.get('data_source', 'Unknown')

        observations.append({
            'mjd': obs_mjd,
            'phase': obs_mjd - discovery_mjd,
            'report_mjd': report_mjd,
            'report_phase': report_mjd - discovery_mjd,
            'mag': at.get('discovery_mag'),
            'filter': filt,
            'survey': survey,
            'is_detection': True,
        })

    # 2. LC Summaries (may contain non-detections)
    for lc in tns_info.get('light_curves', []):
        html_str = lc.get('filter', '') + ' ' + lc.get('telescope', '')
        nondet = parse_nondet_from_html(html_str, discovery_mjd)

        if nondet:
            survey = nondet.get('survey', 'Unknown')

            # Assign report_phase based on first detection from same survey
            report_phase = survey_report_times.get(survey)
            if report_phase:
                report_phase = report_phase - discovery_mjd
            else:
                # Default to first report
                if observations:
                    report_phase = min(o['report_phase'] for o in observations if o['is_detection'])
                else:
                    report_phase = 0

            observations.append({
                'mjd': nondet['mjd'],
                'phase': nondet['phase'],
                'report_mjd': discovery_mjd + report_phase,
                'report_phase': report_phase,
                'mag': None,
                'limiting_mag': nondet.get('limiting_mag'),  # 实际探测极限星等
                'filter': nondet['filter'],
                'survey': survey,
                'is_detection': False,
            })

    return observations


def extract_features(observations, ned_info, tns_info, report_phase_cutoff, source_sky=None):
    """Extract features from visible observations"""
    features = {}
    source_name = tns_info.get('sn_name', '')
    ned = ned_info.get(source_name, {})

    source_sky = source_sky or {}

    # NED host info (safe to use - pre-discovery)
    features['has_ned_host'] = 1 if pd.notna(ned.get('ned_host_name')) else 0
    host_type = ned.get('host_type', 'Unknown')
    features['host_type'] = host_type if pd.notna(host_type) else 'Unknown'

    # Redshift - ONLY use host_z to avoid potential spectroscopic leakage from sn_z
    # sn_z 可能来自爆发后拍摄的光谱，存在时间上的信息泄露风险
    host_z = ned.get('host_redshift')
    tns_z = tns_info.get('redshift')  # Usually host or photometric redshift

    z = None
    z_source = 'default'

    if host_z is not None and pd.notna(host_z):
        try:
            z = float(host_z)
            if 0 < z < 1:
                z_source = 'host_spectroscopic'
            else:
                z = None
        except (ValueError, TypeError):
            z = None

    if z is None and tns_z is not None and pd.notna(tns_z):
        try:
            z = float(tns_z)
            if 0 < z < 1:
                z_source = 'tns_reported'
            else:
                z = None
        except (ValueError, TypeError):
            z = None

    if z is None:
        z = 0.05
        z_source = 'default'

    features['redshift'] = z
    features['redshift_source'] = z_source
    # New sky-context features (batch precomputed, no leakage)
    features['galactic_b'] = source_sky.get('galactic_b', np.nan)
    features['mw_ebv'] = source_sky.get('mw_ebv', np.nan)

    # Distance modulus
    c, H0 = 299792.458, 70.0
    d_L = c * z / H0 * (1 + z / 2)
    features['distance_modulus'] = 5 * np.log10(d_L * 1e6 / 10) if d_L > 0 else 35

    # Split observations
    detections = [o for o in observations if o['is_detection']]
    nondetections = [o for o in observations if not o['is_detection']]

    features['n_det'] = len(detections)
    features['n_nondet'] = len(nondetections)
    features['n_total'] = len(observations)
    features['report_phase_cutoff'] = report_phase_cutoff

    # Magnitude features - 只考虑合理 phase 范围内的观测
    PHASE_VALID_MIN = -30
    PHASE_VALID_MAX = 100

    valid_detections = [o for o in detections if PHASE_VALID_MIN <= o['phase'] <= PHASE_VALID_MAX]
    all_mags = [safe_float(o['mag']) for o in valid_detections if safe_float(o.get('mag')) is not None]
    all_phases = [o['phase'] for o in valid_detections]

    if all_mags:
        features['mag_brightest'] = min(all_mags)
        features['mag_faintest'] = max(all_mags)
        features['mag_range'] = features['mag_faintest'] - features['mag_brightest']
        features['mag_first'] = all_mags[0]
        features['abs_mag_brightest'] = features['mag_brightest'] - features['distance_modulus']
    else:
        features['mag_brightest'] = 20
        features['mag_faintest'] = 20
        features['mag_range'] = 0
        features['mag_first'] = 20
        features['abs_mag_brightest'] = -18

    # Phase features
    if all_phases:
        features['first_det_phase'] = min(all_phases)
        features['last_det_phase'] = max(all_phases)
        features['det_phase_span'] = features['last_det_phase'] - features['first_det_phase']
    else:
        features['first_det_phase'] = 0
        features['last_det_phase'] = 0
        features['det_phase_span'] = 0

    # Non-detection features - 只考虑合理 phase 范围内的观测
    # 改进：考虑波段灵敏度，不只是简单取最晚的非探测
    valid_nondetections = [o for o in nondetections if PHASE_VALID_MIN <= o['phase'] <= PHASE_VALID_MAX]
    nondet_phases = [o['phase'] for o in valid_nondetections]

    # 波段典型灵敏度（用于没有 limiting_mag 时的 fallback）
    BAND_DEPTH = {
        'g-ZTF': 20.8, 'r-ZTF': 20.5, 'i-ZTF': 20.0,
        'cyan-ATLAS': 19.7, 'orange-ATLAS': 19.5,
        'G-Gaia': 20.5, 'g-Sloan': 18.5, 'Clear': 18.0,
    }

    if nondet_phases:
        # 基础特征：最晚/最早的非探测 phase（向后兼容）
        features['last_nondet_phase'] = max(nondet_phases)
        features['first_nondet_phase'] = min(nondet_phases)

        # 改进：找"最有约束力"的非探测
        # 约束力 = phase 越晚越好 + limiting_mag 越深越好
        # 使用加权评分: score = phase + 0.5 * (limiting_mag - 19)
        best_constraint_score = -999
        best_constraint_phase = features['last_nondet_phase']
        best_constraint_filter = 'Unknown'
        best_constraint_lim_mag = None

        for nd in valid_nondetections:
            phase = nd['phase']
            lim_mag = nd.get('limiting_mag')
            filt = nd.get('filter', 'Unknown')

            # 如果没有 limiting_mag，用波段典型深度
            if lim_mag is None:
                lim_mag = BAND_DEPTH.get(filt, 19.0)

            # 计算约束力评分
            # phase 更晚 = 约束更紧 (系数 1.0)
            # limiting_mag 更深 = 约束更强 (系数 0.3，标准化到 19 mag)
            score = phase + 0.3 * (lim_mag - 19.0)

            if score > best_constraint_score:
                best_constraint_score = score
                best_constraint_phase = phase
                best_constraint_filter = filt
                best_constraint_lim_mag = lim_mag

        features['best_constraint_phase'] = best_constraint_phase
        features['best_constraint_filter'] = best_constraint_filter
        features['best_constraint_depth'] = best_constraint_lim_mag if best_constraint_lim_mag else 19.0

        if all_phases:
            # pre_det: 第一次探测之前的非探测
            pre_det = [p for p in nondet_phases if p < min(all_phases)]
            if pre_det:
                features['gap_nondet_to_det'] = min(all_phases) - max(pre_det)
                features['texp_upper_constraint'] = max(pre_det)
            else:
                features['gap_nondet_to_det'] = 0
                features['texp_upper_constraint'] = min(all_phases) - 5
        else:
            features['gap_nondet_to_det'] = 0
            features['texp_upper_constraint'] = -10
    else:
        features['last_nondet_phase'] = 0
        features['first_nondet_phase'] = 0
        features['best_constraint_phase'] = 0
        features['best_constraint_filter'] = 'None'
        features['best_constraint_depth'] = 19.0
        features['gap_nondet_to_det'] = 0
        features['texp_upper_constraint'] = -10

    # ========== 改进的物理先验特征 (v4) ==========
    # 四个改进：
    # 1. 跨 filter 约束：不同 filter 的 nondet→det 也能提供弱约束
    # 2. 灵敏度差异：g 波段比 r/i 波段更灵敏，nondet 约束力不同
    # 3. 全局先验兜底：即使没有 filter 约束，全局边界也被使用
    # 4. **使用实际 limiting_mag**：越深的极限，约束力越强

    PHASE_MIN_FOR_PRIOR = -30
    PHASE_MAX_FOR_PRIOR = 30

    # 波段灵敏度权重（作为 fallback，当没有 limiting_mag 时使用）
    FILTER_SENSITIVITY = {
        'g': 1.0, 'g-ZTF': 1.0, 'g-ATLAS': 1.0, 'cyan': 0.95, 'c': 0.95,
        'r': 0.85, 'r-ZTF': 0.85, 'orange': 0.8, 'o': 0.8,
        'i': 0.7, 'i-ZTF': 0.7,
    }
    DEFAULT_SENSITIVITY = 0.5

    # 典型极限星等（用于归一化 limiting_mag 权重）
    # 越深（数值越大）= 约束力越强
    TYPICAL_LIMITING_MAG = {
        'ZTF': 20.5,
        'ATLAS': 19.5,
        'GaiaAlerts': 20.0,
        'Pan-STARRS': 21.5,
    }
    DEFAULT_TYPICAL_MAG = 19.5

    def get_sensitivity_from_limiting_mag(obs, filter_sensitivity_map):
        """
        计算基于 limiting_mag 的灵敏度权重
        - 有 limiting_mag：直接使用，越深约束越强
        - 无 limiting_mag：fallback 到波段灵敏度
        """
        lim_mag = obs.get('limiting_mag')
        filt = obs.get('filter', 'Unknown')
        survey = obs.get('survey', 'Unknown')

        if lim_mag is not None and lim_mag > 0:
            # 用 limiting_mag 计算权重
            # 归一化：lim_mag 越大（越深），权重越高
            # 典型范围 17-22 mag，归一化到 0.5-1.0
            typical = TYPICAL_LIMITING_MAG.get(survey, DEFAULT_TYPICAL_MAG)
            # 如果 lim_mag >= typical，权重 = 1.0
            # 如果 lim_mag < typical，权重按比例下降
            weight = min(lim_mag / typical, 1.2)  # cap at 1.2
            return weight
        else:
            # Fallback 到波段灵敏度
            return filter_sensitivity_map.get(filt, DEFAULT_SENSITIVITY)

    # 1. 按 filter 分组观测，并记录每个 nondet 的灵敏度
    filter_data = {}
    nondet_details = []  # 记录每个 nondet 的详细信息

    for obs in observations:
        if obs['phase'] < PHASE_MIN_FOR_PRIOR or obs['phase'] > PHASE_MAX_FOR_PRIOR:
            continue
        filt = obs.get('filter', 'Unknown')
        if filt not in filter_data:
            filter_data[filt] = {'nondets': [], 'dets': [], 'sensitivity': FILTER_SENSITIVITY.get(filt, DEFAULT_SENSITIVITY)}
        if obs.get('is_detection', True):
            filter_data[filt]['dets'].append(obs['phase'])
        else:
            filter_data[filt]['nondets'].append(obs['phase'])
            # 记录 nondet 详细信息（包括基于 limiting_mag 的灵敏度）
            sensitivity = get_sensitivity_from_limiting_mag(obs, FILTER_SENSITIVITY)
            nondet_details.append({
                'phase': obs['phase'],
                'filter': filt,
                'limiting_mag': obs.get('limiting_mag'),
                'sensitivity': sensitivity,
            })

    # 2. 全局先验（兜底）
    all_det_phases = []
    all_nondet_phases = []
    for filt, data in filter_data.items():
        all_det_phases.extend(data['dets'])
        all_nondet_phases.extend(data['nondets'])

    # 全局下界：first_det 之前的最后一个 nondet
    if all_det_phases and all_nondet_phases:
        first_det_global = min(all_det_phases)
        pre_det_nondets = [p for p in all_nondet_phases if p < first_det_global]
        if pre_det_nondets:
            global_lower = max(pre_det_nondets)
        else:
            global_lower = first_det_global - 10
    elif all_nondet_phases:
        global_lower = max(all_nondet_phases)
    else:
        global_lower = -10

    # 全局上界：第一个探测（不超过 0）
    if all_det_phases:
        global_upper = min(min(all_det_phases), 0)
    else:
        global_upper = 0

    global_span = max(global_upper - global_lower, 0.1)

    features['prior_lower_bound'] = global_lower
    features['prior_upper_bound'] = global_upper
    features['prior_span'] = global_span
    features['prior_confidence'] = 1.0 / (1.0 + global_span / 5.0)

    # 3. 同 filter 内的约束（强约束）
    n_same_filter_constraints = 0
    same_filter_tightest = 100
    for filt, data in filter_data.items():
        if data['dets'] and data['nondets']:
            first_det_f = min(data['dets'])
            pre_nondets_f = [p for p in data['nondets'] if p < first_det_f]
            if pre_nondets_f:
                span_f = first_det_f - max(pre_nondets_f)
                n_same_filter_constraints += 1
                same_filter_tightest = min(same_filter_tightest, span_f)

    features['n_same_filter_constraints'] = n_same_filter_constraints
    features['same_filter_tightest'] = same_filter_tightest if n_same_filter_constraints > 0 else global_span

    # 4. 跨 filter 约束（弱约束）
    # 场景：filter A 有 nondet，filter B 有 det，nondet 在 det 之前
    # 使用实际 limiting_mag 来加权（如果有）
    cross_filter_lower = global_lower
    cross_filter_weight = 0.0
    cross_filter_lim_mag = None  # 记录最佳约束的 limiting_mag

    if all_det_phases:
        first_det_any = min(all_det_phases)
        # 找所有在 first_det 之前的 nondet（来自任何 filter）
        # 使用 nondet_details 里记录的基于 limiting_mag 的灵敏度
        for nd in nondet_details:
            nondet_phase = nd['phase']
            if nondet_phase < first_det_any:
                sensitivity = nd['sensitivity']
                # 优先选择：1) phase 更晚（更接近 det）2) 灵敏度更高
                if nondet_phase > cross_filter_lower or \
                   (nondet_phase == cross_filter_lower and sensitivity > cross_filter_weight):
                    cross_filter_lower = nondet_phase
                    cross_filter_weight = sensitivity
                    cross_filter_lim_mag = nd['limiting_mag']

    features['cross_filter_lower'] = cross_filter_lower
    features['cross_filter_weight'] = cross_filter_weight  # 0~1.2，越高约束越可信
    features['best_nondet_lim_mag'] = cross_filter_lim_mag if cross_filter_lim_mag else 19.0  # 记录最佳约束的极限星等
    # New feature: depth-window combined non-detection constraint proxy
    depth_mag = max(features['best_nondet_lim_mag'] - 18.0, 0.0)
    gap_days = max(features.get('gap_nondet_to_det', 0.0), 0.0)
    window_weight = 1.0 / (1.0 + gap_days / 3.0)
    features['nondet_constraint_snr'] = depth_mag * window_weight

    # 5. 综合约束：结合同 filter 和跨 filter
    # 如果有同 filter 约束，用它；否则用跨 filter 约束
    if n_same_filter_constraints > 0:
        effective_lower = global_lower  # 同 filter 约束已经体现在 global_lower
        constraint_strength = 1.0
    elif cross_filter_weight > 0:
        effective_lower = cross_filter_lower
        constraint_strength = cross_filter_weight  # 弱约束
    else:
        effective_lower = global_lower
        constraint_strength = 0.3  # 无约束时的默认强度

    features['effective_lower'] = effective_lower
    features['constraint_strength'] = constraint_strength

    # 6. 有效约束跨度
    effective_span = global_upper - effective_lower
    if effective_span <= 0:
        effective_span = 10
    features['effective_span'] = effective_span
    features['effective_confidence'] = constraint_strength / (1.0 + effective_span / 5.0)

    # 兼容旧字段名（step3_train_model.py 使用这些）
    features['n_constraining_filters'] = n_same_filter_constraints
    features['tightest_filter_span'] = features['same_filter_tightest']
    features['texp_tightest_lower'] = effective_lower
    features['texp_tightest_upper'] = global_upper
    features['texp_tightest_gap'] = effective_span

    # 7. 最新观测的约束贡献
    valid_obs = [o for o in observations
                 if PHASE_MIN_FOR_PRIOR <= o['phase'] <= PHASE_MAX_FOR_PRIOR]

    if valid_obs:
        sorted_obs = sorted(valid_obs, key=lambda x: x.get('report_phase', x['phase']))
        latest = sorted_obs[-1]
        features['latest_is_det'] = 1 if latest.get('is_detection', True) else 0
        features['latest_phase'] = latest['phase']
        latest_filter = latest.get('filter', 'Unknown')
        features['latest_sensitivity'] = FILTER_SENSITIVITY.get(latest_filter, DEFAULT_SENSITIVITY)

        # 最新观测是否收紧了约束？
        if features['latest_is_det']:
            features['latest_tightens_bound'] = 1 if latest['phase'] < global_upper else 0
        else:
            features['latest_tightens_bound'] = 1 if effective_lower < latest['phase'] < global_upper else 0
    else:
        features['latest_is_det'] = 0
        features['latest_phase'] = 0
        features['latest_sensitivity'] = DEFAULT_SENSITIVITY
        features['latest_tightens_bound'] = 0

    # 6. det/nondet 比例
    features['det_ratio'] = features['n_det'] / features['n_total'] if features['n_total'] > 0 else 0.5

    # ========== 显式不确定性特征（帮助 CI 收敛） ==========
    # Q10/Q90 模型需要明确知道"信息量越大，不确定性越小"
    n_obs = features['n_total']
    n_det = features['n_det']
    phase_span = features['det_phase_span']

    # 信息量特征（越大=信息越多=不确定性应该越小）
    features['info_score'] = n_obs  # 直接用观测数
    features['info_log'] = np.log1p(n_obs)  # 对数衰减
    features['inv_n_obs'] = 1.0 / (1 + n_obs)  # 倒数（越小=信息越多）

    # 先验不确定性估计（基于物理规律）
    # 观测越多 + 时间跨度越长 = 不确定性越小
    base_uncertainty = 8.0  # 基准不确定性（天）
    n_factor = 1.0 / np.sqrt(1 + n_det)  # 观测数的衰减因子
    span_factor = 1.0 / (1 + phase_span / 10)  # 时间跨度的衰减因子
    features['uncertainty_prior'] = base_uncertainty * n_factor * span_factor

    # 相位覆盖率：检测覆盖了多少时间范围
    if features['first_det_phase'] < 0:
        features['phase_coverage'] = abs(features['first_det_phase']) + features['last_det_phase']
    else:
        features['phase_coverage'] = max(0, features['last_det_phase'] - features['first_det_phase'])

    # 约束紧致度：先验约束的紧程度
    features['constraint_tightness'] = 1.0 / (1 + features['effective_span'] / 3)

    # ========== 形态特征 (参考 MASTER_CLASSIFICATION_DOCUMENT.md) ==========

    # Magnitude slope (斜率)
    if len(all_mags) >= 2 and len(set(all_phases)) >= 2:
        try:
            slope, intercept, r_value, p_value, std_err = scipy_stats.linregress(all_phases, all_mags)
            features['mag_slope'] = slope
            features['is_rising'] = 1 if slope < 0 else 0
            features['slope_r2'] = r_value ** 2  # 拟合优度
        except (ValueError, RuntimeError):
            features['mag_slope'] = 0
            features['is_rising'] = 1
            features['slope_r2'] = 0
    else:
        features['mag_slope'] = 0
        features['is_rising'] = 1
        features['slope_r2'] = 0

    # 光变曲线统计量 (skew, kurtosis) - 需要至少3个点
    if len(all_mags) >= 3:
        features['mag_skew'] = scipy_stats.skew(all_mags)
        features['mag_kurtosis'] = scipy_stats.kurtosis(all_mags)
    else:
        features['mag_skew'] = 0
        features['mag_kurtosis'] = 0

    # 上升/下降速率 (基于峰值前后的点)
    if len(all_mags) >= 2 and len(all_phases) >= 2:
        # 找到最亮点（最小 mag）的位置
        peak_idx = np.argmin(all_mags)
        peak_phase = all_phases[peak_idx]
        peak_mag = all_mags[peak_idx]

        # 上升段：peak_phase 之前的点
        pre_peak_idx = [i for i, p in enumerate(all_phases) if p < peak_phase]
        # 下降段：peak_phase 之后的点
        post_peak_idx = [i for i, p in enumerate(all_phases) if p > peak_phase]

        # 上升速率 (mag/day, 负值表示变亮)
        if len(pre_peak_idx) >= 1:
            earliest_idx = pre_peak_idx[np.argmin([all_phases[i] for i in pre_peak_idx])]
            dt_rise = peak_phase - all_phases[earliest_idx]
            dm_rise = peak_mag - all_mags[earliest_idx]
            features['rise_rate'] = dm_rise / dt_rise if dt_rise > 0 else 0
            features['t_to_peak'] = dt_rise
        else:
            features['rise_rate'] = 0
            features['t_to_peak'] = 0

        # 下降速率 (mag/day, 正值表示变暗)
        if len(post_peak_idx) >= 1:
            latest_idx = post_peak_idx[np.argmax([all_phases[i] for i in post_peak_idx])]
            dt_decline = all_phases[latest_idx] - peak_phase
            dm_decline = all_mags[latest_idx] - peak_mag
            features['decline_rate'] = dm_decline / dt_decline if dt_decline > 0 else 0
            features['t_from_peak'] = dt_decline
        else:
            features['decline_rate'] = 0
            features['t_from_peak'] = 0

        # 类 dm15：峰后某时间的衰减幅度
        # 由于数据稀疏，用实际观测的衰减幅度代替
        if len(post_peak_idx) >= 1:
            features['dm_post_peak'] = all_mags[latest_idx] - peak_mag
        else:
            features['dm_post_peak'] = 0
    else:
        features['rise_rate'] = 0
        features['decline_rate'] = 0
        features['t_to_peak'] = 0
        features['t_from_peak'] = 0
        features['dm_post_peak'] = 0

    # Stetson J 变异性指数 (需要误差信息，这里用简化版本)
    if len(all_mags) >= 2:
        mag_mean = np.mean(all_mags)
        mag_std = np.std(all_mags)
        if mag_std > 0:
            # 简化版 Stetson J：基于残差符号的一致性
            residuals = (np.array(all_mags) - mag_mean) / mag_std
            # 连续残差的乘积（衡量变化的一致性）
            if len(residuals) >= 2:
                sign_products = residuals[:-1] * residuals[1:]
                features['stetson_j_approx'] = np.mean(sign_products)
            else:
                features['stetson_j_approx'] = 0
        else:
            features['stetson_j_approx'] = 0
    else:
        features['stetson_j_approx'] = 0

    # 振幅特征 (amp = max - min)
    if len(all_mags) >= 2:
        features['amp'] = max(all_mags) - min(all_mags)
    else:
        features['amp'] = 0

    # ========== 颜色特征 (参考 MASTER_CLASSIFICATION_DOCUMENT.md) ==========
    # 收集各波段的星等和相位
    band_data = {}  # {band_key: [(phase, mag), ...]}
    for o in detections:
        wl, survey = get_filter_info(o.get('filter'))
        key = f"{survey}_{wl}"
        mag_val = safe_float(o.get('mag'))
        phase = o.get('phase', 0)
        if mag_val is not None:
            if key not in band_data:
                band_data[key] = []
            band_data[key].append((phase, mag_val))

    # 按波长排序波段
    if len(band_data) >= 2:
        try:
            sorted_bands = sorted(band_data.items(), key=lambda x: int(x[0].split('_')[1]))
            blue_band = sorted_bands[0]  # 最蓝波段
            red_band = sorted_bands[-1]  # 最红波段

            # 1. color_mean: 平均颜色 (blue - red)
            features['color_mean'] = np.mean([m for _, m in blue_band[1]]) - np.mean([m for _, m in red_band[1]])

            # 2. color_at_peak: 峰值附近的颜色
            # 找到最接近峰值相位的观测
            peak_phase = all_phases[np.argmin(all_mags)] if all_mags else 0

            def get_nearest_mag(band_points, target_phase):
                if not band_points:
                    return None
                nearest = min(band_points, key=lambda x: abs(x[0] - target_phase))
                return nearest[1]

            blue_at_peak = get_nearest_mag(blue_band[1], peak_phase)
            red_at_peak = get_nearest_mag(red_band[1], peak_phase)
            if blue_at_peak is not None and red_at_peak is not None:
                features['color_at_peak'] = blue_at_peak - red_at_peak
            else:
                features['color_at_peak'] = features['color_mean']

            # 3. color_evolution: 颜色随时间的变化率
            # 计算早期和晚期的颜色差异
            blue_phases = [p for p, _ in blue_band[1]]
            red_phases = [p for p, _ in red_band[1]]

            if len(blue_phases) >= 2 and len(red_phases) >= 2:
                # 早期颜色 (phase < median)
                median_phase = np.median(all_phases) if all_phases else 0
                early_blue = [m for p, m in blue_band[1] if p < median_phase]
                early_red = [m for p, m in red_band[1] if p < median_phase]
                late_blue = [m for p, m in blue_band[1] if p >= median_phase]
                late_red = [m for p, m in red_band[1] if p >= median_phase]

                if early_blue and early_red and late_blue and late_red:
                    early_color = np.mean(early_blue) - np.mean(early_red)
                    late_color = np.mean(late_blue) - np.mean(late_red)
                    phase_span = max(all_phases) - min(all_phases) if all_phases else 1
                    features['color_evolution'] = (late_color - early_color) / max(phase_span, 1)
                else:
                    features['color_evolution'] = 0
            else:
                features['color_evolution'] = 0

            # 4. color_blue_red: 保持兼容
            features['color_blue_red'] = features['color_mean']

        except (ValueError, IndexError):
            features['color_mean'] = 0
            features['color_at_peak'] = 0
            features['color_evolution'] = 0
            features['color_blue_red'] = 0
    else:
        features['color_mean'] = 0
        features['color_at_peak'] = 0
        features['color_evolution'] = 0
        features['color_blue_red'] = 0

    # 波段数量
    features['n_bands'] = len(band_data)

    # Survey features
    surveys = set()
    for o in detections:
        _, survey = get_filter_info(o.get('filter'))
        surveys.add(survey)
    features['n_surveys'] = len(surveys)
    features['has_ztf'] = 1 if 'ZTF' in surveys else 0
    features['has_atlas'] = 1 if 'ATLAS' in surveys else 0

    # ========== 具体颜色特征 (g-r, r-i, c-o) ==========
    # 按标准化波段名分组
    color_band_data = {}  # {band: [(phase, mag), ...]}
    for o in detections:
        filt = o.get('filter', 'unknown')
        mag_val = safe_float(o.get('mag'))
        phase = o.get('phase', 0)
        if mag_val is None or not np.isfinite(mag_val):
            continue

        # 标准化波段名
        filt_lower = str(filt).lower()
        if 'g' in filt_lower and 'ztf' in filt_lower:
            band_key = 'g'
        elif 'r' in filt_lower and 'ztf' in filt_lower:
            band_key = 'r'
        elif 'i' in filt_lower and 'ztf' in filt_lower:
            band_key = 'i'
        elif 'orange' in filt_lower or ('o' in filt_lower and 'atlas' in filt_lower):
            band_key = 'o'
        elif 'cyan' in filt_lower or ('c' in filt_lower and 'atlas' in filt_lower):
            band_key = 'c'
        else:
            continue

        if band_key not in color_band_data:
            color_band_data[band_key] = []
        color_band_data[band_key].append((phase, mag_val))

    # 计算颜色
    def compute_color(b1, b2):
        if b1 in color_band_data and b2 in color_band_data:
            if len(color_band_data[b1]) > 0 and len(color_band_data[b2]) > 0:
                m1 = np.mean([m for _, m in color_band_data[b1]])
                m2 = np.mean([m for _, m in color_band_data[b2]])
                return m1 - m2
        return np.nan

    features['color_g_r'] = compute_color('g', 'r')
    features['color_r_i'] = compute_color('r', 'i')
    features['color_g_i'] = compute_color('g', 'i')
    features['color_c_o'] = compute_color('c', 'o')  # ATLAS: cyan - orange

    # 颜色演化：晚期 - 早期
    if 'g' in color_band_data and 'r' in color_band_data:
        g_sorted = sorted(color_band_data['g'], key=lambda x: x[0])
        r_sorted = sorted(color_band_data['r'], key=lambda x: x[0])
        if len(g_sorted) >= 2 and len(r_sorted) >= 2:
            early_gr = g_sorted[0][1] - r_sorted[0][1]
            late_gr = g_sorted[-1][1] - r_sorted[-1][1]
            features['color_g_r_evolution'] = late_gr - early_gr
        else:
            features['color_g_r_evolution'] = np.nan
    else:
        features['color_g_r_evolution'] = np.nan

    # 各波段统计
    for band in ['g', 'r', 'i', 'o', 'c']:
        if band in color_band_data and len(color_band_data[band]) > 0:
            mags = [m for _, m in color_band_data[band]]
            features[f'mag_{band}_mean'] = np.mean(mags)
            features[f'mag_{band}_min'] = np.min(mags)
            features[f'n_obs_{band}'] = len(mags)
        else:
            features[f'mag_{band}_mean'] = np.nan
            features[f'mag_{band}_min'] = np.nan
            features[f'n_obs_{band}'] = 0

    # ========== Bazin/PowerLaw 拟合特征 ==========
    # 为每个波段尝试拟合，提取物理参数
    try:
        bazin_texp_list = []
        bazin_texp_unc_list = []

        for band in ['g', 'r', 'i', 'o', 'c']:
            if band not in color_band_data or len(color_band_data[band]) < 4:
                continue

            phases_b = np.array([p for p, _ in color_band_data[band]])
            mags_b = np.array([m for _, m in color_band_data[band]])

            # 转换为 flux
            flux_b = np.power(10, -0.4 * (mags_b - 20))
            flux_err_b = flux_b * 0.1  # 假设 10% 误差

            # 尝试简单的线性 rise 拟合（更稳定）
            # 只用上升段
            peak_idx = np.argmax(flux_b)
            if peak_idx > 0:
                p_rise = phases_b[:peak_idx + 1]
                f_rise = flux_b[:peak_idx + 1]

                if len(p_rise) >= 2:
                    try:
                        slope, intercept, r_val, _, _ = scipy_stats.linregress(p_rise, f_rise)
                        if slope > 0:
                            texp_est = -intercept / slope
                            # 质量检查
                            if -30 < texp_est < phases_b[0] and r_val**2 > 0.5:
                                bazin_texp_list.append(texp_est)
                                # 不确定度用 r^2 的倒数近似
                                bazin_texp_unc_list.append(1.0 / max(r_val**2, 0.1))
                    except Exception:
                        pass

            # 存储该波段的斜率信息
            if len(phases_b) >= 2:
                try:
                    slope_all, _, r_all, _, _ = scipy_stats.linregress(phases_b, mags_b)
                    features[f'slope_{band}'] = slope_all  # 负值 = 变亮
                    features[f'slope_{band}_r2'] = r_all**2
                except Exception:
                    features[f'slope_{band}'] = np.nan
                    features[f'slope_{band}_r2'] = np.nan
            else:
                features[f'slope_{band}'] = np.nan
                features[f'slope_{band}_r2'] = np.nan

        # 聚合 Bazin texp
        if bazin_texp_list:
            features['bazin_texp_median'] = np.median(bazin_texp_list)
            features['bazin_texp_std'] = np.std(bazin_texp_list) if len(bazin_texp_list) > 1 else 0
            features['bazin_n_bands'] = len(bazin_texp_list)

            # 加权平均
            if bazin_texp_unc_list:
                weights = 1.0 / (np.array(bazin_texp_unc_list) + 0.01)
                features['bazin_texp_weighted'] = np.average(bazin_texp_list, weights=weights)
            else:
                features['bazin_texp_weighted'] = features['bazin_texp_median']
        else:
            features['bazin_texp_median'] = np.nan
            features['bazin_texp_std'] = np.nan
            features['bazin_n_bands'] = 0
            features['bazin_texp_weighted'] = np.nan

    except Exception:
        features['bazin_texp_median'] = np.nan
        features['bazin_texp_std'] = np.nan
        features['bazin_n_bands'] = 0
        features['bazin_texp_weighted'] = np.nan

    # ========== 增强特征 (基于高MAE样本分析) ==========
    # 1. 观测密度: n_total / phase_span
    if features.get('det_phase_span', 0) > 0:
        features['obs_density'] = features['n_total'] / features['det_phase_span']
    else:
        features['obs_density'] = features['n_total']

    # 2. 检测比率 (安全版)
    features['det_ratio_safe'] = features['n_det'] / max(features['n_total'], 1)

    # 3. 约束质量评分
    if 'constraint_strength' in features and 'effective_span' in features:
        features['constraint_quality'] = features['constraint_strength'] / (1 + features['effective_span'] / 5)
    else:
        features['constraint_quality'] = 0.5

    # 4. 多巡天覆盖指标
    features['multi_survey'] = features.get('has_ztf', 0) + features.get('has_atlas', 0)

    # 5. 振幅调整的上升速率 (rise_quality) - 高MAE分析中最重要的新特征
    if 'rise_rate' in features and 'mag_range' in features:
        features['rise_quality'] = abs(features['rise_rate']) * (1 + features['mag_range'])
    else:
        features['rise_quality'] = 0

    # 6. 信息完整度评分
    features['info_completeness'] = np.log1p(features['n_det']) * np.log1p(features['n_nondet'] + 1) * features['n_bands']

    return features


def load_ned_info():
    """Load NED host galaxy info"""
    ned_file = DATA_DIR / "merged_ned_info.csv"
    if not ned_file.exists():
        print(f"  Warning: {ned_file} not found")
        return {}
    df = pd.read_csv(ned_file)
    ned_info = {}
    for _, row in df.iterrows():
        ned_info[row['source_name']] = {
            'ned_host_name': row.get('ned_host_name'),
            'host_type': row.get('host_type'),
            'host_redshift': row.get('host_redshift'),
            'sn_redshift': row.get('sn_redshift'),
        }
    return ned_info


def load_host_features():
    """Load host galaxy features from integrated data"""
    host_file = DATA_DIR / "host_features.csv"
    if not host_file.exists():
        print(f"  Warning: {host_file} not found")
        return {}
    df = pd.read_csv(host_file)
    host_info = {}
    for _, row in df.iterrows():
        host_info[row['source_name']] = {
            'host_offset_arcsec': row.get('host_offset_arcsec'),
            'host_offset_kpc': row.get('host_offset_kpc'),
            'host_z': row.get('host_z'),
            'host_gr': row.get('host_gr'),
            'log_host_mass': row.get('log_host_mass'),
            'host_catalog': row.get('catalog'),
        }
    print(f"  Loaded {len(host_info)} host feature entries")
    return host_info


def load_extra_features():
    """Load extra features from host data bundle (Gaia, WISE, DLR)"""
    HOST_DIR = DATA_DIR / 'host'
    extra_features = {}

    # 1. Load Gaia features
    gaia_file = HOST_DIR / 'gaia' / 'gaia_final.csv'
    if gaia_file.exists():
        gaia = pd.read_csv(gaia_file)
        for _, row in gaia.iterrows():
            source = row['source_name']
            if source not in extra_features:
                extra_features[source] = {}
            extra_features[source]['gaia_parallax'] = row['parallax'] if pd.notna(row['parallax']) else 0
            extra_features[source]['gaia_pm'] = row['pm'] if pd.notna(row['pm']) else 0
            # Stellar indicator: parallax > 0.2 mas and parallax_error/parallax < 0.2
            if pd.notna(row['parallax']) and pd.notna(row['parallax_error']) and row['parallax'] > 0:
                if row['parallax'] > 0.2 and row['parallax_error'] / row['parallax'] < 0.2:
                    extra_features[source]['gaia_is_stellar'] = 1
                else:
                    extra_features[source]['gaia_is_stellar'] = 0
            else:
                extra_features[source]['gaia_is_stellar'] = 0
        print(f"    Gaia: {len(gaia)} entries")

    # 2. Load WISE W1-W2 from host_candidates_long
    hc_file = HOST_DIR / 'combined' / 'host_candidates_long.csv'
    if hc_file.exists():
        hc = pd.read_csv(hc_file, usecols=['source_name', 'w1_mag', 'w2_mag', 'flux_w1', 'flux_w2', 'sep_arcsec'], low_memory=False)
        wise_count = 0
        for source, group in hc.groupby('source_name'):
            if source not in extra_features:
                extra_features[source] = {}

            # Try w1_mag/w2_mag first (GLADE catalog)
            has_mag = group['w1_mag'].notna() & group['w2_mag'].notna()
            if has_mag.any():
                valid = group[has_mag].sort_values('sep_arcsec')
                row = valid.iloc[0]
                w1w2 = row['w1_mag'] - row['w2_mag']
                extra_features[source]['wise_w1w2'] = w1w2
                extra_features[source]['wise_is_agn'] = 1 if w1w2 >= 0.8 else 0
                wise_count += 1
            # Fallback to flux_w1/flux_w2 (Legacy Survey)
            elif (group['flux_w1'].notna() & group['flux_w2'].notna()).any():
                valid = group[group['flux_w1'].notna() & group['flux_w2'].notna()].sort_values('sep_arcsec')
                row = valid.iloc[0]
                if row['flux_w1'] > 0 and row['flux_w2'] > 0:
                    w1_mag = 22.5 - 2.5 * np.log10(row['flux_w1'])
                    w2_mag = 22.5 - 2.5 * np.log10(row['flux_w2'])
                    w1w2 = w1_mag - w2_mag
                    extra_features[source]['wise_w1w2'] = w1w2
                    extra_features[source]['wise_is_agn'] = 1 if w1w2 >= 0.8 else 0
                    wise_count += 1
        print(f"    WISE: {wise_count} entries")

    # 3. Load DLR from ML dataset
    ml_file = HOST_DIR / 'ml' / 'gold_features_dataset.csv'
    if ml_file.exists():
        ml = pd.read_csv(ml_file)
        dlr_count = 0
        for _, row in ml.iterrows():
            source = row['source_name']
            if source not in extra_features:
                extra_features[source] = {}
            if pd.notna(row.get('dlr')):
                extra_features[source]['host_dlr'] = row['dlr']
                extra_features[source]['host_log_dlr'] = np.log10(row['dlr'] + 0.01) if row['dlr'] > 0 else -2
                dlr_count += 1
        print(f"    DLR: {dlr_count} entries")

    print(f"  Total extra features for {len(extra_features)} sources")
    return extra_features


def build_dataset(
    sources_df,
    tns_data,
    ned_info,
    host_info=None,
    extra_info=None,
    sky_info=None,
    clip_target_to_zero=True
):
    """Build dynamic samples dataset"""
    all_samples = []
    host_info = host_info or {}
    extra_info = extra_info or {}
    sky_info = sky_info or {}
    
    # Merged data directory for forced photometry non-detection
    merged_dir = DATA_DIR / 'merged'

    for idx, row in sources_df.iterrows():
        source_name = row['source_name']
        texp_final = row['texp_final']

        tns_info = tns_data.get(source_name, {})
        tns_info['sn_name'] = source_name

        if not tns_info or len(tns_info.get('at_reports', [])) == 0:
            continue

        all_obs = extract_full_observations(tns_info)
        if len(all_obs) == 0:
            continue
        
        # 将 forced photometry non-detection 作为普通观测点添加
        # 这样处理的好处：模型不依赖特殊特征，没有forced数据时也能正常运行
        merged_csv = merged_dir / f"{source_name}.csv"
        discovery_mjd = tns_info.get('discovery_mjd')
        
        if merged_csv.exists():
            # 提取各波段的 forced non-detection
            # 注意：只需要传递 csv 路径，phase_min 和 phase_max 使用默认值
            forced_nondet_bands = extract_forced_nondet_per_band(merged_csv)
            
            # 获取第一个 TNS 报告的 report_phase（forced数据在此时同步获得）
            first_report_phase = min(o['report_phase'] for o in all_obs)
            first_report_mjd = discovery_mjd + first_report_phase if discovery_mjd else None
            
            # 将每个波段的 last non-detection 作为普通观测点添加
            for band, info in forced_nondet_bands.items():
                if info.get('has_nondet') and info.get('last_nondet_phase') is not None:
                    # 确保 phase < 0（发现之前），避免信息泄露
                    nondet_phase = info['last_nondet_phase']
                    if nondet_phase < 0:
                        all_obs.append({
                            'mjd': info.get('last_nondet_mjd'),
                            'phase': nondet_phase,
                            'report_mjd': first_report_mjd,
                            'report_phase': first_report_phase,  # 与第一个报告同时获得
                            'mag': None,
                            'limiting_mag': info.get('limiting_mag'),
                            'filter': band.replace('_', '-'),  # ZTF_g -> ZTF-g
                            'survey': 'ZTF' if 'ZTF' in band else ('ATLAS' if 'ATLAS' in band else 'Forced'),
                            'is_detection': False,
                            'source': 'forced_photometry',  # 标记来源
                        })

        # Get unique report phases
        report_phases = sorted(set(o['report_phase'] for o in all_obs))

        # Get host features for this source
        host_feats = host_info.get(source_name, {})
        extra_feats = extra_info.get(source_name, {})

        # Create a sample at each report phase
        for sample_idx, rp in enumerate(report_phases):
            visible = [o for o in all_obs if o['report_phase'] <= rp]
            if len(visible) == 0:
                continue

            source_sky = sky_info.get(source_name, {})
            features = extract_features(visible, ned_info, tns_info, rp, source_sky=source_sky)
            features['source_name'] = source_name
            # Targets:
            # - target_raw: original label from Step1 (may be > 0 depending on definition/fit)
            # - target_clipped: enforce physical constraint texp <= 0 (strict mode)
            target_raw = float(texp_final)
            target_clipped = min(target_raw, 0.0)
            features['target_raw'] = target_raw
            features['target_clipped'] = target_clipped
            features['target'] = target_clipped if clip_target_to_zero else target_raw
            features['sample_idx'] = sample_idx + 1
            features['observations'] = visible  # For visualization

            # Add host galaxy features
            features['host_offset_arcsec'] = host_feats.get('host_offset_arcsec', np.nan)
            features['host_offset_kpc'] = host_feats.get('host_offset_kpc', np.nan)
            features['host_gr'] = host_feats.get('host_gr', np.nan)
            features['log_host_mass'] = host_feats.get('log_host_mass', np.nan)
            features['has_host_match'] = 1 if host_feats else 0

            # Add extra features (Gaia, WISE, DLR)
            features['gaia_parallax'] = extra_feats.get('gaia_parallax', 0)
            features['gaia_pm'] = extra_feats.get('gaia_pm', 0)
            features['gaia_is_stellar'] = extra_feats.get('gaia_is_stellar', 0)
            features['wise_w1w2'] = extra_feats.get('wise_w1w2', 0)
            features['wise_is_agn'] = extra_feats.get('wise_is_agn', 0)
            features['host_dlr'] = extra_feats.get('host_dlr', 0)
            features['host_log_dlr'] = extra_feats.get('host_log_dlr', -2)

            # === Discovery boundary features (让模型知道 texp <= 0) ===
            # 距离 discovery 的"安全距离"：first_det_phase 越负，texp 可能越负
            first_det = features.get('first_det_phase', 0)
            features['dist_to_discovery'] = -first_det  # 正值表示"有空间"预测更负的 texp
            # 是否是"边界样本"：first_det 接近 0，意味着 texp 也应该接近 0
            features['near_discovery'] = 1 if abs(first_det) < 0.5 else 0
            # 显式的物理上界（虽然是常数，但在数据中显式呈现）
            features['texp_physical_upper'] = 0.0
            
            # NOTE: Forced photometry non-detection 已作为普通观测点处理
            # 不再需要特殊特征，extract_features 自然会计算 last_nondet_phase 等

            all_samples.append(features)

        if (idx + 1) % 200 == 0:
            print(f"  Processed {idx + 1}/{len(sources_df)} sources...")

    return all_samples


def main():
    parser = argparse.ArgumentParser(description='Step2: build dynamic samples from TNS report times')
    parser.add_argument(
        '--no-clip-target',
        action='store_true',
        help='Do NOT clip target to <= 0 (i.e., use raw texp_final as training target)'
    )
    parser.add_argument(
        '--stages',
        default='1,2,3',
        help='Comma-separated stages to include (default: 1,2,3)'
    )
    parser.add_argument(
        '--drop-clipped-target',
        action='store_true',
        help='Drop sources with texp_final >= 0 (would be clipped or sit at 0)'
    )
    args = parser.parse_args()

    print("=" * 70)
    print("STEP 2: BUILD DYNAMIC SAMPLES FROM TNS REPORT TIMES")
    print("=" * 70)

    # Load sources
    print("\n[1] Loading sources...")
    sources_file = DATA_DIR / 'sources.csv'
    if not sources_file.exists():
        print(f"  ERROR: {sources_file} not found! Run Step 1 first.")
        return

    sources_df = pd.read_csv(sources_file)
    stages = [int(x.strip()) for x in args.stages.split(',') if x.strip()]
    s23 = sources_df[sources_df['stage'].isin(stages)].copy().reset_index(drop=True)

    n_stage23 = sources_df[sources_df['stage'].isin(stages)].shape[0]
    n_removed_stage2 = len(sources_df) - len(s23)
    print(f"  Total sources: {len(sources_df)}")
    print(f"  Included stages: {stages}")
    print(f"  Stage-filtered sources: {n_stage23}")
    print(f"  Removed by stage filter: {n_removed_stage2}")

    if args.drop_clipped_target:
        before = len(s23)
        texp_vals = pd.to_numeric(s23['texp_final'], errors='coerce')
        s23 = s23[texp_vals < 0].copy().reset_index(drop=True)
        dropped = before - len(s23)
        print(f"  Dropped positive texp sources: {dropped}")

    print(f"  Sources for training: {len(s23)}")

    # Load TNS data
    print("\n[2] Loading TNS data...")
    tns_file = DATA_DIR / 'tns/parsed/tns_full_info.json'
    if not tns_file.exists():
        print(f"  ERROR: {tns_file} not found!")
        return

    with open(tns_file, 'r', encoding='utf-8') as f:
        tns_data = json.load(f)
    print(f"  Loaded {len(tns_data)} TNS entries")

    # Load NED info
    print("\n[3] Loading NED host info...")
    ned_info = load_ned_info()
    print(f"  Loaded {len(ned_info)} NED entries")

    # Load host features
    print("\n[3.5] Loading host galaxy features...")
    host_info = load_host_features()

    # Load extra features (Gaia, WISE, DLR)
    print("\n[3.6] Loading extra features (Gaia, WISE, DLR)...")
    extra_info = load_extra_features()

    # Load sky features (RA/Dec -> galactic_b + IRSA E(B-V))
    print("\n[3.7] Building sky features (mw_ebv, galactic_b)...")
    merged_dir = DATA_DIR / 'merged'
    source_names = list(s23['source_name'].astype(str).values)
    sky_info = build_sky_feature_cache(source_names, merged_dir, max_workers=8)

    # Build samples
    print("\n[4] Building dynamic samples...")
    clip_target_to_zero = not args.no_clip_target
    print(f"  Target mode: {'clip_to_0' if clip_target_to_zero else 'raw'}")
    all_samples = build_dataset(
        s23,
        tns_data,
        ned_info,
        host_info=host_info,
        extra_info=extra_info,
        sky_info=sky_info,
        clip_target_to_zero=clip_target_to_zero
    )
    print(f"  Total samples: {len(all_samples)}")

    # Save
    output_file = DATA_DIR / 'dynamic_samples.pkl'
    with open(output_file, 'wb') as f:
        pickle.dump(all_samples, f)
    print(f"\n  Samples saved: {output_file}")

    # Statistics
    n_sources = len(set(s['source_name'] for s in all_samples))
    avg_samples = len(all_samples) / n_sources if n_sources > 0 else 0
    print(f"\n[5] Statistics:")
    print(f"  Sources with samples: {n_sources}")
    print(f"  Average samples per source: {avg_samples:.1f}")

    print("\n" + "=" * 70)
    print("STEP 2 COMPLETE!")
    print("=" * 70)


if __name__ == "__main__":
    main()

