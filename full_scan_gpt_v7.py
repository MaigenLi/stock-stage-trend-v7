#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V7 启动捕捉策略 - 增强版

改进：
1. 使用通达信离线数据目录 ~/stock_data/vipdoc/
2. 使用股票代码文件 ~/stock_code/results/stock_codes.txt
3. 工作目录固定在 ~/.openclaw/workspace/stock_stage_trend/
4. 输出加入股票名称和板块信息
5. 支持 limit / 全量扫描 / 结果排序保存
"""

import os
import re
import sys
import json
import struct
import argparse
from threading import RLock
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import requests
import warnings

warnings.filterwarnings('ignore', message='Unverified HTTPS request')

TDX_DATA_DIR = os.path.expanduser("~/stock_data/vipdoc/")
STOCK_CODES_FILE = os.path.expanduser("~/stock_code/results/stock_codes.txt")
WORK_DIR = os.path.expanduser("~/.openclaw/workspace/stock_stage_trend/")
RESULTS_DIR = os.path.join(WORK_DIR, "results")
CACHE_DIR = os.path.join(WORK_DIR, "sector_cache")
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
STOCK_NAME_CACHE_FILE = os.path.join(WORK_DIR, "stock_name_cache.json")
STOCK_NAME_CACHE_CANDIDATES = [
    STOCK_NAME_CACHE_FILE,
]

os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

# 只使用当前项目内置的板块模块，不再依赖 stock_trend 项目
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)
from stock_sector import get_sector_info

COMMON_STOCKS = {
    'sh600519': '贵州茅台', 'sz000001': '平安银行', 'sz002460': '赣锋锂业',
    'sh600036': '招商银行', 'sz000858': '五粮液', 'sh600030': '中信证券',
    'sz300750': '宁德时代', 'sh600276': '恒瑞医药', 'sh600000': '浦发银行',
    'sh600016': '民生银行', 'sh600028': '中国石化', 'sh600031': '三一重工',
    'sh600048': '保利发展', 'sh600050': '中国联通', 'sh600104': '上汽集团',
    'sh600309': '万华化学', 'sh600547': '山东黄金', 'sh600585': '海螺水泥',
    'sh600690': '海尔智家', 'sh600837': '海通证券', 'sh600887': '伊利股份',
    'sh600900': '长江电力', 'sh601318': '中国平安', 'sh601328': '交通银行',
    'sh601398': '工商银行', 'sh601668': '中国建筑', 'sh601857': '中国石油',
    'sh601919': '中远海控', 'sh601988': '中国银行', 'sz000002': '万科A',
    'sz000063': '中兴通讯', 'sz000333': '美的集团', 'sz002230': '科大讯飞',
    'sz002415': '海康威视', 'sz002475': '立讯精密', 'sz002594': '比亚迪',
    'sz300059': '东方财富', 'sz300760': '迈瑞医疗'
}

SECTOR_KEYWORDS = {
    '新能源': ['新能源', '光伏', '风电', '储能', '电池', '锂电', '锂业', '太阳能'],
    '医药': ['医药', '制药', '生物', '医疗', '药业', '健康'],
    '科技': ['科技', '技术', '软件', '信息', '电子', '通信', '智能', '网络', '数据'],
    '消费': ['酒', '食品', '饮料', '餐饮', '零售', '百货', '消费'],
    '金融': ['银行', '证券', '保险', '信托', '金融', '投资'],
    '制造': ['制造', '工业', '机械', '设备', '工程', '重工'],
    '资源': ['矿业', '金属', '矿产', '资源', '煤炭', '石油', '钢铁'],
}

SECTOR_CATEGORY = {
    '新能源': '科技', '医药': '医疗', '科技': '科技', '消费': '消费',
    '金融': '金融', '制造': '制造', '资源': '资源', '白酒Ⅱ': '消费',
    '银行': '金融', '保险': '金融', '证券': '金融', '能源金属': '资源',
    '化学制药': '医疗'
}

HOT_SECTORS = {'白酒Ⅱ', '新能源', '人工智能', '芯片', '医药', '光伏', '锂电池'}
MEDIUM_SECTORS = {'银行', '保险', '证券', '消费', '汽车', '家电', '房地产', '能源金属', '化学制药'}

STOCK_NAME_CACHE_LOCK = RLock()
STOCK_NAME_CACHE = None


def read_tdx_day(code: str):
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
            d = data[i:i+32]
            if len(d) < 32:
                continue
            rows.append([
                struct.unpack('I', d[0:4])[0],
                struct.unpack('I', d[4:8])[0] / 100.0,
                struct.unpack('I', d[8:12])[0] / 100.0,
                struct.unpack('I', d[12:16])[0] / 100.0,
                struct.unpack('I', d[16:20])[0] / 100.0,
                struct.unpack('I', d[24:28])[0],
            ])
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=['date_int', 'open', 'high', 'low', 'close', 'volume'])
        df['date'] = pd.to_datetime(df['date_int'].astype(str))
        df = df.sort_values('date').reset_index(drop=True)
        df = df[(df['close'] > 0) & (df['volume'] > 0)]
        return df
    except Exception:
        return None


def _load_stock_name_cache():
    global STOCK_NAME_CACHE
    with STOCK_NAME_CACHE_LOCK:
        if STOCK_NAME_CACHE is not None:
            return STOCK_NAME_CACHE

        merged_cache = {}
        for cache_file in STOCK_NAME_CACHE_CANDIDATES:
            if not os.path.exists(cache_file):
                continue
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        merged_cache.update(data)
            except Exception:
                continue

        STOCK_NAME_CACHE = merged_cache
        return STOCK_NAME_CACHE


def _cache_stock_name(code: str, name: str):
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
    return COMMON_STOCKS.get(code, '未知')


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
    return normalized_name.startswith('ST') or normalized_name.startswith('*ST')


def _sector_hotness_popularity(sector: str):
    if sector in HOT_SECTORS:
        return 70, 80
    if sector in MEDIUM_SECTORS:
        return 50, 60
    return 40, 40


def infer_sector_from_name(name: str):
    if not name or name == '未知':
        return {
            'main_sector': '未知', 'sector_hotness': 40, 'sector_popularity': 30,
            'sector_category': '其他', 'source': 'inferred'
        }
    for sector, words in SECTOR_KEYWORDS.items():
        if any(word in name for word in words):
            hotness, popularity = _sector_hotness_popularity(sector)
            return {
                'main_sector': sector,
                'sector_hotness': hotness,
                'sector_popularity': popularity,
                'sector_category': SECTOR_CATEGORY.get(sector, '其他'),
                'source': 'inferred'
            }
    return {
        'main_sector': '其他', 'sector_hotness': 40, 'sector_popularity': 30,
        'sector_category': '其他', 'source': 'inferred'
    }


def _normalize_sector_info(sector_info: dict, name: str = ''):
    if not sector_info:
        return infer_sector_from_name(name)

    hotness = sector_info.get('sector_hotness', sector_info.get('hotness', 40))
    popularity = sector_info.get('sector_popularity', sector_info.get('popularity', 30))

    try:
        hotness = int(round(float(hotness)))
    except Exception:
        hotness = 40

    try:
        popularity = int(round(float(popularity)))
    except Exception:
        popularity = 30

    return {
        'main_sector': sector_info.get('main_sector', '未知'),
        'sector_hotness': hotness,
        'sector_popularity': popularity,
        'sector_category': sector_info.get('sector_category', sector_info.get('category', '其他')),
        'source': sector_info.get('source', 'unknown'),
    }


def get_stock_sector_info(code: str, name: str = ''):
    try:
        sector_info = get_sector_info().get_stock_sector_info(code, name)
        return _normalize_sector_info(sector_info, name)
    except Exception:
        pass

    cache_file = os.path.join(CACHE_DIR, f'{code}.json')
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    try:
        if code.startswith('sh'):
            market, stock_code = 'sh', code[2:]
        elif code.startswith('sz'):
            market, stock_code = 'sz', code[2:]
        else:
            return infer_sector_from_name(name)

        url = f'http://quote.eastmoney.com/{market}{stock_code}.html'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'http://quote.eastmoney.com/',
        }
        r = requests.get(url, headers=headers, timeout=3, verify=False)
        if r.status_code == 200:
            m = re.search(r'var quotedata = ({[^}]+})', r.text)
            if m:
                quotedata = json.loads(m.group(1))
                sector = quotedata.get('bk_name', '未知')
                hotness, popularity = _sector_hotness_popularity(sector)
                result = {
                    'main_sector': sector,
                    'sector_hotness': hotness,
                    'sector_popularity': popularity,
                    'sector_category': SECTOR_CATEGORY.get(sector, '其他'),
                    'source': 'eastmoney'
                }
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                return result
    except Exception:
        pass

    result = infer_sector_from_name(name)
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return result


def calc_signal(df):
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


def backtest(df):
    if len(df) < 40:
        return 0
    returns = []
    for i in range(30, len(df) - 2):
        sub_df = df.iloc[:i + 1]
        signal, _ = calc_signal(sub_df)
        if signal:
            buy_price = df['open'].iloc[i + 1]
            sell_price = df['close'].iloc[i + 2]
            returns.append((sell_price - buy_price) / buy_price)
    return np.mean(returns) if returns else 0


def load_stock_codes(limit: int = 100, all_stocks: bool = False):
    codes = []
    with open(STOCK_CODES_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and (line.startswith('sh') or line.startswith('sz')):
                codes.append(line)
    if all_stocks or limit <= 0:
        return codes
    return codes[:limit]


def evaluate_stock(code: str):
    df = read_tdx_day(code)
    if df is None or len(df) < 40:
        return None

    signal, score = calc_signal(df)
    bt_ret = backtest(df) if signal else 0
    latest_price = df['close'].iloc[-1]
    latest_change = (df['close'].iloc[-1] - df['close'].iloc[-2]) / df['close'].iloc[-2] * 100
    three_day_change = (df['close'].iloc[-1] - df['close'].iloc[-3]) / df['close'].iloc[-3] * 100 if len(df) >= 3 else 0

    # 只对候选股票走网络名称/板块获取，避免全量扫描时对全部股票发请求
    name = get_stock_name(code, allow_network=signal)

    # 排除 ST / *ST 股票，避免进入候选结果
    if is_st_stock(name):
        return None

    if signal:
        sector_info = get_stock_sector_info(code, name)
    else:
        sector_info = infer_sector_from_name(name)

    return {
        'code': code,
        'name': name,
        'signal': signal,
        'score': score,
        'backtest_return': bt_ret,
        'latest_price': latest_price,
        'latest_change': latest_change,
        'three_day_change': three_day_change,
        **sector_info,
    }


def run_screening(codes, workers=8):
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


def save_results(results, scanned_count):
    signal_results = [r for r in results if r['signal']]
    signal_results.sort(key=lambda x: (-x['score'], -x['backtest_return']))

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    result_path = os.path.join(RESULTS_DIR, f'v7_candidates_{ts}.txt')
    code_path = os.path.join(RESULTS_DIR, f'v7_candidates_{ts}_codes.txt')

    with open(result_path, 'w', encoding='utf-8') as f:
        f.write('# V7 启动捕捉策略结果\n')
        f.write(f'# 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
        f.write(f'# 扫描股票: {scanned_count}只\n')
        f.write(f'# 候选股票: {len(signal_results)}只\n\n')
        for r in signal_results:
            f.write(f"{r['code']} {r['name']}\n")
            f.write(f"  评分: {r['score']} 回测收益: {r['backtest_return']:.4f}\n")
            f.write(f"  价格: {r['latest_price']:.2f} 涨跌: {r['latest_change']:+.2f}% 三天: {r['three_day_change']:+.2f}%\n")
            f.write(f"  板块: {r['main_sector']} ({r['sector_category']})\n")
            f.write(f"  热度: {r['sector_hotness']} 人气: {r['sector_popularity']} 来源: {r['source']}\n\n")

    with open(code_path, 'w', encoding='utf-8') as f:
        for r in signal_results:
            f.write(f"{r['code']}\n")

    return result_path, code_path, signal_results


def main():
    parser = argparse.ArgumentParser(description='V7 启动捕捉策略增强版')
    parser.add_argument('--limit', type=int, default=100, help='扫描股票数量，0表示全量')
    parser.add_argument('--all', action='store_true', help='扫描全部股票')
    parser.add_argument('--workers', type=int, default=8, help='并发线程数')
    args = parser.parse_args()

    print('=' * 80)
    print('📈 V7 启动捕捉策略 - 增强版')
    print('=' * 80)
    print(f'数据目录: {TDX_DATA_DIR}')
    print(f'股票代码文件: {STOCK_CODES_FILE}')
    print(f'工作目录: {WORK_DIR}')
    print(f'板块模块: {os.path.join(CURRENT_DIR, "stock_sector.py")}')
    print()

    codes = load_stock_codes(limit=args.limit, all_stocks=args.all)
    print(f'扫描股票数量: {len(codes)}只')
    print('⏳ 开始筛选...')

    results = run_screening(codes, workers=args.workers)
    result_path, code_path, signal_results = save_results(results, len(codes))

    print(f'\n✅ 筛选完成')
    print(f'处理股票: {len(codes)}只')
    print(f'候选股票: {len(signal_results)}只')

    if signal_results:
        print('\n🎯 候选股票前10：')
        for i, r in enumerate(signal_results[:10], 1):
            print(f"{i:2d}. {r['code']} {r['name']} | 分数:{r['score']} | 回测:{r['backtest_return']:.2%} | 板块:{r['main_sector']}")
    else:
        print('未找到符合条件的股票')

    print(f'\n结果文件: {result_path}')
    print(f'代码文件: {code_path}')
    print('=' * 80)


if __name__ == '__main__':
    main()
