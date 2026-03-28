#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V7 启动捕捉策略 - 混合增强版

特性：
1. 使用通达信离线数据目录 ~/stock_data/vipdoc/
2. 使用股票代码文件 ~/stock_code/results/stock_codes.txt
3. 工作目录固定在 ~/.openclaw/workspace/stock_stage_trend/
4. 输出加入股票名称和板块信息
5. 支持 limit / 全量扫描 / 结果排序保存
6. 自动排除 ST / *ST 股票
7. 仅依赖当前项目内置模块，不再依赖其它项目
8. 融合趋势过滤、三天表现过滤、十天风险控制与简化回测统计
"""

import os
import re
import json
import struct
import argparse
from threading import RLock
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import warnings

from stock_names import STOCK_NAME_MAP
from stock_sector import get_sector_info

warnings.filterwarnings('ignore', message='Unverified HTTPS request')

TDX_DATA_DIR = os.path.expanduser("~/stock_data/vipdoc/")
STOCK_CODES_FILE = os.path.expanduser("~/stock_code/results/stock_codes.txt")
WORK_DIR = os.path.expanduser("~/.openclaw/workspace/stock_stage_trend/")
RESULTS_DIR = os.path.join(WORK_DIR, "results")
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
STOCK_NAME_CACHE_FILE = os.path.join(WORK_DIR, "stock_name_cache.json")

os.makedirs(RESULTS_DIR, exist_ok=True)

PRESET_PARAMS: Dict[str, Dict[str, object]] = {
    'aggressive': {
        'min_price': 2.0,
        'max_price': 200.0,
        'min_three_day_change': 2.0,
        'max_three_day_change': 30.0,
        'min_up_days': 2,
        'min_avg_volume_ratio': 0.9,
        'max_ten_day_change': 45.0,
        'min_latest_amount': 5e7,
        'min_avg_amount_5': 5e7,
        'require_above_ma10': False,
        'require_ma_trend': False,
    },
    'balanced': {
        'min_price': 3.0,
        'max_price': 200.0,
        'min_three_day_change': 3.0,
        'max_three_day_change': 25.0,
        'min_up_days': 2,
        'min_avg_volume_ratio': 1.0,
        'max_ten_day_change': 35.0,
        'min_latest_amount': 1e8,
        'min_avg_amount_5': 1e8,
        'require_above_ma10': False,
        'require_ma_trend': False,
    },
    'conservative': {
        'min_price': 5.0,
        'max_price': 200.0,
        'min_three_day_change': 4.0,
        'max_three_day_change': 20.0,
        'min_up_days': 3,
        'min_avg_volume_ratio': 1.1,
        'max_ten_day_change': 25.0,
        'min_latest_amount': 3e8,
        'min_avg_amount_5': 3e8,
        'require_above_ma10': True,
        'require_ma_trend': True,
    },
}
DEFAULT_PRESET = 'balanced'
DEFAULT_PARAMS: Dict[str, object] = PRESET_PARAMS[DEFAULT_PRESET].copy()
STRATEGY_PARAMS: Dict[str, object] = DEFAULT_PARAMS.copy()

STOCK_NAME_CACHE_LOCK = RLock()
STOCK_NAME_CACHE: Optional[Dict[str, str]] = None


def read_tdx_day(code: str) -> Optional[pd.DataFrame]:
    if code.startswith('sh'):
        market, code_num = 'sh', code[2:]
    elif code.startswith('sz'):
        market, code_num = 'sz', code[2:]
    else:
        return None

    path = os.path.join(TDX_DATA_DIR, market, 'lday', f'{market}{code_num}.day')
    if not os.path.exists(path):
        return None

    try:
        with open(path, 'rb') as f:
            data = f.read()

        rows = []
        for i in range(0, len(data), 32):
            d = data[i:i + 32]
            if len(d) < 32:
                continue
            rows.append([
                struct.unpack('I', d[0:4])[0],
                struct.unpack('I', d[4:8])[0] / 100.0,
                struct.unpack('I', d[8:12])[0] / 100.0,
                struct.unpack('I', d[12:16])[0] / 100.0,
                struct.unpack('I', d[16:20])[0] / 100.0,
                float(struct.unpack('f', d[20:24])[0]),
                struct.unpack('I', d[24:28])[0],
            ])

        if not rows:
            return None

        df = pd.DataFrame(rows, columns=['date_int', 'open', 'high', 'low', 'close', 'amount', 'volume'])
        df['date'] = pd.to_datetime(df['date_int'].astype(str))
        df = df.sort_values('date').reset_index(drop=True)
        df = df[(df['close'] > 0) & (df['volume'] > 0) & (df['amount'] > 0)]
        return df
    except Exception:
        return None


def _load_stock_name_cache() -> Dict[str, str]:
    global STOCK_NAME_CACHE
    with STOCK_NAME_CACHE_LOCK:
        if STOCK_NAME_CACHE is not None:
            return STOCK_NAME_CACHE

        if not os.path.exists(STOCK_NAME_CACHE_FILE):
            STOCK_NAME_CACHE = {}
            return STOCK_NAME_CACHE

        try:
            with open(STOCK_NAME_CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            STOCK_NAME_CACHE = data if isinstance(data, dict) else {}
        except Exception:
            STOCK_NAME_CACHE = {}

        return STOCK_NAME_CACHE


def _cache_stock_name(code: str, name: str) -> None:
    if not name or name == '未知':
        return

    with STOCK_NAME_CACHE_LOCK:
        cache = _load_stock_name_cache()
        if cache.get(code) == name:
            return
        cache[code] = name
        try:
            with open(STOCK_NAME_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


def _get_stock_name_from_local(code: str) -> str:
    cache = _load_stock_name_cache()
    if code in cache and cache[code]:
        return cache[code]
    return STOCK_NAME_MAP.get(code, '未知')


def _get_stock_name_from_sina(code: str) -> str:
    try:
        if code.startswith('sh'):
            api_code = f'sh{code[2:]}'
        elif code.startswith('sz'):
            api_code = f'sz{code[2:]}'
        else:
            return '未知'

        url = f'http://hq.sinajs.cn/list={api_code}'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'http://finance.sina.com.cn/',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        response = requests.get(url, headers=headers, timeout=3, verify=False)
        if response.status_code == 200 and response.text:
            match = re.search(r'="([^"]+)"', response.text)
            if match:
                parts = match.group(1).split(',')
                if parts and parts[0].strip():
                    name = parts[0].strip()
                    if name not in {'', 'null', 'NULL', 'None'}:
                        _cache_stock_name(code, name)
                        return name
    except Exception:
        pass
    return '未知'


def _get_stock_name_from_eastmoney(code: str) -> str:
    try:
        if code.startswith('sh'):
            market, stock_code = 'sh', code[2:]
        elif code.startswith('sz'):
            market, stock_code = 'sz', code[2:]
        else:
            return '未知'

        url = f'http://quote.eastmoney.com/{market}{stock_code}.html'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'http://quote.eastmoney.com/',
        }
        response = requests.get(url, headers=headers, timeout=3, verify=False)
        if response.status_code != 200:
            return '未知'

        match = re.search(r'var quotedata = ({[^}]+})', response.text)
        if match:
            try:
                quotedata = json.loads(match.group(1))
                name = quotedata.get('name', '').strip()
                if name and name not in {'', 'null', 'NULL', 'None'}:
                    _cache_stock_name(code, name)
                    return name
            except Exception:
                pass

        title_match = re.search(r'<title>([^<]+)</title>', response.text)
        if title_match:
            title = title_match.group(1)
            name_match = re.search(r'^([^(]+)', title)
            if name_match:
                name = name_match.group(1).strip()
                if name and len(name) < 20:
                    _cache_stock_name(code, name)
                    return name
    except Exception:
        pass
    return '未知'


def get_stock_name(code: str, allow_network: bool = True) -> str:
    local_name = _get_stock_name_from_local(code)
    if local_name != '未知' or not allow_network:
        return local_name

    name = _get_stock_name_from_sina(code)
    if name != '未知':
        return name

    return _get_stock_name_from_eastmoney(code)


def is_st_stock(name: str) -> bool:
    if not name or name == '未知':
        return False

    normalized_name = name.strip().upper().replace(' ', '')
    return normalized_name.startswith('*ST') or normalized_name.startswith('ST')


def format_amount_yi(amount: float) -> str:
    return f'{amount / 1e8:.2f}亿'


def resolve_strategy_params(args: argparse.Namespace) -> Dict[str, object]:
    params = PRESET_PARAMS[args.preset].copy()

    overrides = {
        'min_price': args.min_price,
        'max_price': args.max_price,
        'min_three_day_change': args.min_three_day_change,
        'max_three_day_change': args.max_three_day_change,
        'min_up_days': args.min_up_days,
        'min_avg_volume_ratio': args.min_avg_volume_ratio,
        'max_ten_day_change': args.max_ten_day_change,
        'min_latest_amount': args.min_latest_amount,
        'min_avg_amount_5': args.min_avg_amount_5,
        'require_above_ma10': args.require_above_ma10,
        'require_ma_trend': args.require_ma_trend,
    }

    for key, value in overrides.items():
        if value is not None:
            params[key] = value

    return params


def get_stock_sector_info(code: str, name: str = '', allow_online: bool = True) -> Dict[str, object]:
    try:
        sector_info = get_sector_info().get_stock_sector_info(code, name, allow_online=allow_online)
    except Exception:
        sector_info = {}

    try:
        hotness = int(round(float(sector_info.get('sector_hotness', 40))))
    except Exception:
        hotness = 40

    try:
        popularity = int(round(float(sector_info.get('sector_popularity', 30))))
    except Exception:
        popularity = 30

    return {
        'main_sector': sector_info.get('main_sector', '未知'),
        'sector_hotness': hotness,
        'sector_popularity': popularity,
        'sector_category': sector_info.get('sector_category', '其他'),
        'source': sector_info.get('source', 'inferred'),
    }


def calc_signal(df: pd.DataFrame) -> Tuple[bool, int]:
    if len(df) < 30:
        return False, 0

    df = df.copy()
    cond_trend = df['low'].rolling(10).min().iloc[-1] > df['low'].rolling(20).min().iloc[-1]
    cond_up = df['close'].iloc[-1] > df['close'].iloc[-2] > df['close'].iloc[-3]
    cond_break = df['close'].iloc[-1] > df['high'].rolling(10).max().iloc[-2]
    cond_vol = df['volume'].iloc[-1] > df['volume'].rolling(5).mean().iloc[-2] * 1.5

    vol_up = df[df['close'] > df['close'].shift(1)]['volume']
    vol_down = df[df['close'] < df['close'].shift(1)]['volume']
    cond_quality = len(vol_up) > 3 and len(vol_down) > 3 and vol_up.tail(5).mean() > vol_down.tail(5).mean()

    body = abs(df['close'].iloc[-1] - df['open'].iloc[-1])
    upper_shadow = df['high'].iloc[-1] - max(df['close'].iloc[-1], df['open'].iloc[-1])
    cond_fake = upper_shadow < body

    amplitude = (df['high'] - df['low']) / df['close']
    cond_squeeze = amplitude.tail(5).mean() < amplitude.tail(20).mean()

    score = 0
    if cond_break:
        score += 2
    if cond_vol:
        score += 2
    if cond_quality:
        score += 2
    if cond_fake:
        score += 2
    if cond_squeeze:
        score += 1

    signal = cond_trend and cond_up and score >= 7
    return signal, score


def analyze_quality_metrics(df: pd.DataFrame) -> Dict[str, float]:
    recent = df.copy()
    recent['ma5'] = recent['close'].rolling(5).mean()
    recent['ma10'] = recent['close'].rolling(10).mean()
    recent['ma20'] = recent['close'].rolling(20).mean()
    recent['vol_ma5'] = recent['volume'].rolling(5).mean()
    recent['amount_ma5'] = recent['amount'].rolling(5).mean()
    recent['volume_ratio'] = recent['volume'] / recent['vol_ma5']
    recent['amount_ratio_5'] = recent['amount'] / recent['amount_ma5']
    recent['change_pct'] = recent['close'].pct_change() * 100

    latest = recent.iloc[-1]
    last_3 = recent.iloc[-3:]
    last_5 = recent.iloc[-5:]

    latest_price = float(latest['close'])
    latest_change = float(latest['change_pct']) if pd.notna(latest['change_pct']) else 0.0
    latest_volume_ratio = float(latest['volume_ratio']) if pd.notna(latest['volume_ratio']) else 0.0
    latest_amount = float(latest['amount']) if pd.notna(latest['amount']) else 0.0
    latest_amount_ratio = float(latest['amount_ratio_5']) if pd.notna(latest['amount_ratio_5']) else 0.0

    start_price_3 = float(last_3.iloc[0]['close'])
    end_price_3 = float(last_3.iloc[-1]['close'])
    three_day_change = (end_price_3 - start_price_3) / start_price_3 * 100 if start_price_3 > 0 else 0.0
    up_days = int((last_3['change_pct'] > 0).sum())
    avg_volume_ratio = float(last_3['volume_ratio'].replace([np.inf, -np.inf], np.nan).fillna(0).mean())
    avg_amount_5 = float(last_5['amount'].replace([np.inf, -np.inf], np.nan).fillna(0).mean()) if len(last_5) > 0 else 0.0

    if len(recent) >= 10:
        start_price_10 = float(recent.iloc[-10]['close'])
        end_price_10 = float(recent.iloc[-1]['close'])
        ten_day_change = (end_price_10 - start_price_10) / start_price_10 * 100 if start_price_10 > 0 else 0.0
    else:
        ten_day_change = 0.0

    trend_strength = float((last_5['change_pct'] > 0).sum() / len(last_5)) if len(last_5) > 0 else 0.0

    ma5 = float(latest['ma5']) if pd.notna(latest['ma5']) else 0.0
    ma10 = float(latest['ma10']) if pd.notna(latest['ma10']) else 0.0
    ma20 = float(latest['ma20']) if pd.notna(latest['ma20']) else 0.0

    return {
        'latest_price': latest_price,
        'latest_change': latest_change,
        'three_day_change': three_day_change,
        'ten_day_change': ten_day_change,
        'up_days': up_days,
        'avg_volume_ratio': avg_volume_ratio,
        'latest_volume_ratio': latest_volume_ratio,
        'latest_amount': latest_amount,
        'avg_amount_5': avg_amount_5,
        'latest_amount_ratio': latest_amount_ratio,
        'trend_strength': trend_strength,
        'ma5': ma5,
        'ma10': ma10,
        'ma20': ma20,
        'price_above_ma10': latest_price > ma10 if ma10 > 0 else False,
        'price_above_ma20': latest_price > ma20 if ma20 > 0 else False,
        'ma5_above_ma10': ma5 > ma10 if ma5 > 0 and ma10 > 0 else False,
        'ma10_above_ma20': ma10 > ma20 if ma10 > 0 and ma20 > 0 else False,
    }


def passes_hybrid_filters(metrics: Dict[str, float]) -> bool:
    if metrics['latest_price'] < float(STRATEGY_PARAMS['min_price']):
        return False
    if metrics['latest_price'] > float(STRATEGY_PARAMS['max_price']):
        return False
    if metrics['three_day_change'] < float(STRATEGY_PARAMS['min_three_day_change']):
        return False
    if metrics['three_day_change'] > float(STRATEGY_PARAMS['max_three_day_change']):
        return False
    if metrics['up_days'] < int(STRATEGY_PARAMS['min_up_days']):
        return False
    if metrics['avg_volume_ratio'] < float(STRATEGY_PARAMS['min_avg_volume_ratio']):
        return False
    if metrics['ten_day_change'] > float(STRATEGY_PARAMS['max_ten_day_change']):
        return False
    if metrics['latest_amount'] < float(STRATEGY_PARAMS['min_latest_amount']):
        return False
    if metrics['avg_amount_5'] < float(STRATEGY_PARAMS['min_avg_amount_5']):
        return False
    if STRATEGY_PARAMS['require_above_ma10'] and not metrics['price_above_ma10']:
        return False
    if STRATEGY_PARAMS['require_ma_trend'] and not (metrics['ma5_above_ma10'] and metrics['ma10_above_ma20']):
        return False
    return True


def calculate_hybrid_score(base_score: int, metrics: Dict[str, float], backtest_info: Dict[str, float]) -> float:
    score = float(base_score)

    three_day_change = metrics['three_day_change']
    if 3.0 <= three_day_change <= 8.0:
        score += 2.0
    elif 8.0 < three_day_change <= 15.0:
        score += 1.5
    elif 15.0 < three_day_change <= 25.0:
        score += 0.5

    avg_volume_ratio = metrics['avg_volume_ratio']
    if avg_volume_ratio >= 1.5:
        score += 2.0
    elif avg_volume_ratio >= 1.2:
        score += 1.0
    elif avg_volume_ratio >= 1.0:
        score += 0.5

    if metrics['latest_volume_ratio'] >= 1.8:
        score += 1.0
    elif metrics['latest_volume_ratio'] >= 1.3:
        score += 0.5

    if metrics['latest_amount_ratio'] >= 1.8:
        score += 1.0
    elif metrics['latest_amount_ratio'] >= 1.3:
        score += 0.5

    if metrics['avg_amount_5'] >= 8e8:
        score += 1.5
    elif metrics['avg_amount_5'] >= 3e8:
        score += 1.0
    elif metrics['avg_amount_5'] >= 1e8:
        score += 0.5

    if metrics['trend_strength'] >= 0.8:
        score += 2.0
    elif metrics['trend_strength'] >= 0.6:
        score += 1.0

    if metrics['price_above_ma10']:
        score += 1.0
    if metrics['ma5_above_ma10']:
        score += 1.0
    if metrics['ma10_above_ma20']:
        score += 1.0

    ten_day_change = metrics['ten_day_change']
    if ten_day_change <= 20.0:
        score += 1.0
    elif ten_day_change <= 30.0:
        score += 0.5

    signal_count = backtest_info['backtest_signal_count']
    if signal_count >= 8:
        score += 1.0
    elif signal_count >= 4:
        score += 0.5

    win_rate = backtest_info['backtest_win_rate']
    if win_rate >= 0.6:
        score += 1.0
    elif win_rate >= 0.5:
        score += 0.5

    return round(score, 2)


def backtest(df: pd.DataFrame) -> Dict[str, float]:
    if len(df) < 40:
        return {
            'backtest_return': 0.0,
            'backtest_signal_count': 0,
            'backtest_win_rate': 0.0,
        }

    returns: List[float] = []
    wins = 0
    for i in range(30, len(df) - 2):
        sub_df = df.iloc[:i + 1]
        signal, _ = calc_signal(sub_df)
        if signal:
            buy_price = float(df['open'].iloc[i + 1])
            sell_price = float(df['close'].iloc[i + 2])
            if buy_price <= 0:
                continue
            ret = (sell_price - buy_price) / buy_price
            returns.append(ret)
            if ret > 0:
                wins += 1

    signal_count = len(returns)
    avg_return = float(np.mean(returns)) if returns else 0.0
    win_rate = float(wins / signal_count) if signal_count else 0.0

    return {
        'backtest_return': avg_return,
        'backtest_signal_count': signal_count,
        'backtest_win_rate': win_rate,
    }


def load_stock_codes(limit: int = 100, all_stocks: bool = False) -> List[str]:
    codes = []
    with open(STOCK_CODES_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and (line.startswith('sh') or line.startswith('sz')):
                codes.append(line)
    if all_stocks or limit <= 0:
        return codes
    return codes[:limit]


def evaluate_stock(code: str) -> Optional[Dict[str, object]]:
    df = read_tdx_day(code)
    if df is None or len(df) < 40:
        return None

    signal, base_score = calc_signal(df)
    if not signal:
        return None

    metrics = analyze_quality_metrics(df)
    if not passes_hybrid_filters(metrics):
        return None

    name = get_stock_name(code, allow_network=True)
    if is_st_stock(name):
        return None

    sector_info = get_stock_sector_info(code, name, allow_online=True)
    backtest_info = backtest(df)
    final_score = calculate_hybrid_score(base_score, metrics, backtest_info)

    return {
        'code': code,
        'name': name,
        'signal': signal,
        'base_score': base_score,
        'score': final_score,
        **metrics,
        **backtest_info,
        **sector_info,
    }


def run_screening(codes: List[str], workers: int = 8) -> List[Dict[str, object]]:
    results = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(evaluate_stock, code): code for code in codes}
        for i, future in enumerate(as_completed(futures), 1):
            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception:
                pass
            if i % 50 == 0:
                print(f'  已处理 {i}/{len(codes)} 只')
    return results


def save_results(results: List[Dict[str, object]], scanned_count: int) -> Tuple[str, str, str, List[Dict[str, object]]]:
    signal_results = [r for r in results if r['signal']]
    signal_results.sort(key=lambda x: (-float(x['score']), -float(x['backtest_return'])))

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    result_path = os.path.join(RESULTS_DIR, f'v7_candidates_{ts}.txt')
    code_path = os.path.join(RESULTS_DIR, f'v7_candidates_{ts}_codes.txt')
    csv_path = os.path.join(RESULTS_DIR, f'v7_candidates_{ts}.csv')

    with open(result_path, 'w', encoding='utf-8') as f:
        f.write('# V7 启动捕捉策略 - 混合增强版结果\n')
        f.write(f'# 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
        f.write(f'# 扫描股票: {scanned_count}只\n')
        f.write(f'# 候选股票: {len(signal_results)}只\n')
        f.write(f'# 参数: {json.dumps(STRATEGY_PARAMS, ensure_ascii=False)}\n\n')
        for r in signal_results:
            f.write(f"{r['code']} {r['name']}\n")
            f.write(f"  评分: {r['score']:.2f} (原始信号:{r['base_score']}) 回测收益: {r['backtest_return']:.4f}\n")
            f.write(f"  回测次数: {r['backtest_signal_count']} 胜率: {r['backtest_win_rate']:.2%}\n")
            f.write(f"  价格: {r['latest_price']:.2f} 涨跌: {r['latest_change']:+.2f}% 三天: {r['three_day_change']:+.2f}% 十天: {r['ten_day_change']:+.2f}%\n")
            f.write(f"  量比: 三日均量比 {r['avg_volume_ratio']:.2f} 当日量比 {r['latest_volume_ratio']:.2f} 趋势强度 {r['trend_strength']:.1%}\n")
            f.write(f"  成交额: 当日 {format_amount_yi(float(r['latest_amount']))} 五日均额 {format_amount_yi(float(r['avg_amount_5']))} 额比 {r['latest_amount_ratio']:.2f}\n")
            f.write(f"  均线: MA5 {r['ma5']:.2f} MA10 {r['ma10']:.2f} MA20 {r['ma20']:.2f}\n")
            f.write(f"  板块: {r['main_sector']} ({r['sector_category']})\n")
            f.write(f"  热度: {r['sector_hotness']} 人气: {r['sector_popularity']} 来源: {r['source']}\n\n")

    with open(code_path, 'w', encoding='utf-8') as f:
        for r in signal_results:
            f.write(f"{r['code']}\n")

    csv_columns = [
        'code', 'name', 'score', 'base_score',
        'backtest_return', 'backtest_signal_count', 'backtest_win_rate',
        'latest_price', 'latest_change', 'three_day_change', 'ten_day_change',
        'up_days', 'avg_volume_ratio', 'latest_volume_ratio', 'latest_amount', 'avg_amount_5', 'latest_amount_ratio', 'trend_strength',
        'ma5', 'ma10', 'ma20',
        'price_above_ma10', 'price_above_ma20', 'ma5_above_ma10', 'ma10_above_ma20',
        'main_sector', 'sector_category', 'sector_hotness', 'sector_popularity', 'source',
    ]
    csv_rows = [{col: r.get(col) for col in csv_columns} for r in signal_results]
    pd.DataFrame(csv_rows, columns=csv_columns).to_csv(csv_path, index=False, encoding='utf-8-sig')

    return result_path, code_path, csv_path, signal_results


def main():
    parser = argparse.ArgumentParser(description='V7 启动捕捉策略 - 混合增强版')
    parser.add_argument('--preset', choices=list(PRESET_PARAMS.keys()), default=DEFAULT_PRESET, help='参数预设：aggressive / balanced / conservative')
    parser.add_argument('--limit', type=int, default=100, help='扫描股票数量，0表示全量')
    parser.add_argument('--all', action='store_true', help='扫描全部股票')
    parser.add_argument('--workers', type=int, default=8, help='并发线程数')

    parser.add_argument('--min-price', type=float, default=None, help='最小价格(元)')
    parser.add_argument('--max-price', type=float, default=None, help='最大价格(元)')
    parser.add_argument('--min-three-day-change', type=float, default=None, help='最小三日涨幅(%)')
    parser.add_argument('--max-three-day-change', type=float, default=None, help='最大三日涨幅(%)')
    parser.add_argument('--min-up-days', type=int, default=None, help='三日内最少上涨天数')
    parser.add_argument('--min-avg-volume-ratio', type=float, default=None, help='最小三日平均量比')
    parser.add_argument('--max-ten-day-change', type=float, default=None, help='最大十日涨幅(%)')
    parser.add_argument('--min-latest-amount', type=float, default=None, help='最小当日成交额(元)')
    parser.add_argument('--min-avg-amount-5', type=float, default=None, help='最小五日平均成交额(元)')
    parser.add_argument('--require-above-ma10', action=argparse.BooleanOptionalAction, default=None, help='是否要求最新价站上 MA10')
    parser.add_argument('--require-ma-trend', action=argparse.BooleanOptionalAction, default=None, help='是否要求 MA5>MA10 且 MA10>MA20')
    args = parser.parse_args()

    global STRATEGY_PARAMS
    STRATEGY_PARAMS = resolve_strategy_params(args)

    print('=' * 80)
    print('📈 V7 启动捕捉策略 - 混合增强版')
    print('=' * 80)
    print(f'数据目录: {TDX_DATA_DIR}')
    print(f'股票代码文件: {STOCK_CODES_FILE}')
    print(f'工作目录: {WORK_DIR}')
    print(f'板块模块: {os.path.join(CURRENT_DIR, "stock_sector.py")}')
    print(f'名称缓存: {STOCK_NAME_CACHE_FILE}')
    print(f'参数预设: {args.preset}')
    print('筛选参数:')
    for key, value in STRATEGY_PARAMS.items():
        print(f'  {key}: {value}')
    print()

    codes = load_stock_codes(limit=args.limit, all_stocks=args.all)
    print(f'扫描股票数量: {len(codes)}只')
    print('⏳ 开始筛选...')

    results = run_screening(codes, workers=args.workers)
    result_path, code_path, csv_path, signal_results = save_results(results, len(codes))

    print(f'\n✅ 筛选完成')
    print(f'处理股票: {len(codes)}只')
    print(f'候选股票: {len(signal_results)}只')

    if signal_results:
        print('\n🎯 候选股票前10：')
        for i, r in enumerate(signal_results[:10], 1):
            print(
                f"{i:2d}. {r['code']} {r['name']} | 分数:{r['score']:.2f} | "
                f"回测:{r['backtest_return']:.2%} | 胜率:{r['backtest_win_rate']:.0%} | 板块:{r['main_sector']}"
            )
    else:
        print('未找到符合条件的股票')

    print(f'\n结果文件: {result_path}')
    print(f'代码文件: {code_path}')
    print(f'CSV文件: {csv_path}')
    print('=' * 80)


if __name__ == '__main__':
    main()
