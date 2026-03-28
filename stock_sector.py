#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票板块信息模块（stock_stage_trend 项目专用版）

目标：
1. 完全自包含，不依赖其它项目
2. 只保留当前项目真正用到的能力
3. 对候选股票提供板块 / 热度 / 人气 / 分类信息
4. 网络失败时可回退到本地名称推断
"""

import json
import os
import random
import re
from datetime import datetime
from typing import Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import warnings

warnings.filterwarnings('ignore', message='Unverified HTTPS request')


class StockSectorInfo:
    """面向当前项目的精简板块信息获取器"""

    def __init__(self, cache_dir: Optional[str] = None):
        if cache_dir is None:
            cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sector_cache')
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        ]

        self.session = self._create_session()
        self._init_sector_data()

    def _create_session(self) -> requests.Session:
        session = requests.Session()

        retry_strategy = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=['GET'],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=20)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        session.headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
        })
        return session

    def _init_sector_data(self):
        self.sector_hotness = {
            '人工智能': 95, 'AI': 95, '芯片': 90, '半导体': 90, '算力': 88,
            '新能源': 85, '光伏': 85, '储能': 83, '锂电池': 82, '新能源汽车': 88,
            '创新药': 82, '医疗器械': 80, '生物医药': 78, '医药': 75,
            '云计算': 84, '大数据': 82, '数字经济': 80, '信创': 78,
            '机器人': 83, '工业母机': 80, '智能制造': 78,
            '白酒': 70, '食品饮料': 65, '消费': 68, '家电': 62,
            '证券': 72, '金融科技': 68, '保险': 60, '银行': 58,
            '有色金属': 68, '稀土': 70, '黄金': 65, '煤炭': 62,
            '电力': 64, '电网': 66, '特高压': 68,
            '军工': 72, '航天航空': 70, '船舶': 65,
            '房地产': 55, '基建': 62, '建筑': 58,
            '化工': 58, '化肥': 56, '化纤': 52,
            '钢铁': 50, '水泥': 48, '建材': 52,
            '汽车': 56, '零部件': 54, '整车': 52,
            '零售': 48, '商贸': 46, '物流': 50,
            '传媒': 54, '游戏': 56, '影视': 50,
            '农业': 52, '种植': 48, '养殖': 50,
            '纺织服装': 38, '轻工制造': 36, '造纸': 34,
            '港口': 32, '航运': 34, '机场': 30,
            '旅游': 42, '酒店': 38, '餐饮': 36,
            '教育': 28, '环保': 40, '公用事业': 35,
        }

        self.sector_categories = {
            '科技': ['人工智能', 'AI', '芯片', '半导体', '算力', '云计算', '大数据', '数字经济', '信创', '5G', '物联网', '区块链', '消费电子'],
            '新能源': ['新能源', '光伏', '储能', '锂电池', '新能源汽车', '氢能源', '风电', '核电', '绿色电力'],
            '医药': ['创新药', '医疗器械', '生物医药', '医药', '中药', '医疗服务', 'CRO', '疫苗'],
            '高端制造': ['机器人', '工业母机', '智能制造', '高端装备', '数控机床', '自动化'],
            '消费': ['白酒', '食品饮料', '消费', '家电', '零售', '商贸', '服装', '化妆品'],
            '金融': ['证券', '金融科技', '保险', '银行', '互联网金融'],
            '周期': ['有色金属', '稀土', '黄金', '煤炭', '化工', '化肥', '化纤', '钢铁', '水泥', '建材'],
            '军工': ['军工', '航天航空', '船舶', '国防', '卫星导航'],
            '基建': ['房地产', '基建', '建筑', '工程机械', '轨道交通'],
            '汽车': ['汽车', '零部件', '整车', '新能源汽车', '智能驾驶'],
            '其他': ['农业', '传媒', '游戏', '影视', '旅游', '酒店', '餐饮', '教育', '环保', '公用事业', '物流', '港口', '航运', '机场'],
        }

        self.sector_popularity = {
            '人工智能': 95, 'AI': 95, '芯片': 92, '新能源': 90, '白酒': 88,
            '医药': 85, '证券': 82, '光伏': 80, '云计算': 78,
            '锂电池': 75, '储能': 72, '机器人': 70, '军工': 68,
            '消费电子': 65, '食品饮料': 62, '有色金属': 60,
            '银行': 45, '保险': 42, '房地产': 40, '煤炭': 38,
            '钢铁': 35, '化工': 40, '建筑': 38,
        }

    def _random_headers(self) -> Dict[str, str]:
        return {
            'User-Agent': random.choice(self.user_agents),
            'Referer': 'http://quote.eastmoney.com/',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
        }

    def _cache_file(self, code: str) -> str:
        return os.path.join(self.cache_dir, f'{code}.json')

    def load_from_cache(self, code: str) -> Optional[Dict]:
        cache_file = self._cache_file(code)
        if not os.path.exists(cache_file):
            return None

        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            cache_time = datetime.fromisoformat(data.get('cache_time', '2000-01-01T00:00:00'))
            if (datetime.now() - cache_time).days < 1:
                return data
        except Exception:
            return None
        return None

    def save_to_cache(self, code: str, data: Dict):
        payload = dict(data)
        payload['cache_time'] = datetime.now().isoformat()
        try:
            with open(self._cache_file(code), 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def fetch_online_sectors(self, code: str) -> Optional[Dict]:
        if code.startswith('sh'):
            market, stock_code = 'sh', code[2:]
        elif code.startswith('sz'):
            market, stock_code = 'sz', code[2:]
        else:
            return None

        url = f'http://quote.eastmoney.com/{market}{stock_code}.html'

        try:
            response = self.session.get(
                url,
                headers=self._random_headers(),
                timeout=(4, 6),
                verify=False,
            )
            if response.status_code != 200:
                return None
        except Exception:
            return None

        html = response.text
        sectors: List[str] = []

        js_match = re.search(r'var quotedata = ({[^}]+})', html)
        if js_match:
            try:
                quotedata = json.loads(js_match.group(1))
                bk_name = quotedata.get('bk_name')
                if bk_name and bk_name not in {'--', '暂无数据', '未知'}:
                    sectors.append(bk_name)
            except Exception:
                pass

        if not sectors:
            industry_patterns = [
                r'所属行业[：:]\s*<a[^>]*>([^<]+)</a>',
                r'行业分类[：:]\s*<a[^>]*>([^<]+)</a>',
                r'industry:"([^"]+)"',
                r'所属行业[：:]\s*([^<]+)',
            ]
            for pattern in industry_patterns:
                match = re.search(pattern, html)
                if match:
                    industry = match.group(1).strip()
                    if industry and industry not in {'--', '暂无数据', '未知'}:
                        sectors.append(industry)
                        break

        concept_patterns = [
            r'概念板块[：:]\s*([^<]+)',
            r'概念题材[：:]\s*([^<]+)',
            r'所属概念[：:]\s*([^<]+)',
            r'concept:"([^"]+)"',
        ]
        for pattern in concept_patterns:
            match = re.search(pattern, html)
            if not match:
                continue
            raw_text = match.group(1).strip()
            if not raw_text or raw_text in {'--', '暂无数据', '未知'}:
                continue
            parts = [raw_text]
            for sep in [' ', ',', '、', '，', ';', '；']:
                if sep in raw_text:
                    parts = [item.strip() for item in raw_text.split(sep) if item.strip()]
                    break
            sectors.extend(parts)
            break

        sectors = list(dict.fromkeys([item for item in sectors if item and len(item) > 1]))
        if not sectors:
            return None

        return {
            'sectors': sectors,
            'source': '10jqka',
        }

    def infer_sector_from_name(self, code: str, name: str) -> Dict:
        if not name or name == '未知':
            if code.startswith('sh'):
                if code[2:].startswith('60'):
                    return {'sectors': ['上证主板'], 'source': 'inferred'}
                if code[2:].startswith('68'):
                    return {'sectors': ['科创板'], 'source': 'inferred'}
            if code.startswith('sz'):
                if code[2:].startswith('00'):
                    return {'sectors': ['深证主板'], 'source': 'inferred'}
                if code[2:].startswith('30'):
                    return {'sectors': ['创业板'], 'source': 'inferred'}
            return {'sectors': [], 'source': 'inferred'}

        name_lower = name.lower()
        sectors = []
        sector_keywords = {
            '银行': ['银行', '农商行', '商业银行', '商行'],
            '证券': ['证券', '券商', '投行', '中信', '华泰', '海通'],
            '保险': ['保险', '人寿', '财险', '太保', '平安'],
            '医药': ['医药', '制药', '生物', '医疗', '健康', '药业', '医院', '器械', '药', '生物技术'],
            '科技': ['科技', '技术', '软件', '信息', '数据', '网络', '电子', '通信', '数码', '智能', 'AI', '人工智能'],
            '新能源': ['新能源', '能源', '光伏', '风电', '储能', '电池', '锂电', '锂业', '太阳能', '清洁能源', '赣锋', '天齐'],
            '汽车': ['汽车', '车', '汽配', '零部件', '整车', '乘用车', '商用车'],
            '消费': ['消费', '食品', '饮料', '酒', '零售', '商超', '百货', '超市', '购物', '餐饮'],
            '房地产': ['地产', '房产', '置业', '物业', '万科', '保利', '招商蛇口'],
            '化工': ['化工', '化学', '材料', '石化', '石油', '化纤'],
            '机械': ['机械', '装备', '设备', '制造', '工程', '重工'],
            '电力': ['电力', '电网', '电气', '能源', '发电', '供电'],
            '建筑': ['建筑', '建设', '工程', '路桥', '中铁', '中建', '交建'],
            '有色': ['有色', '金属', '矿业', '矿', '铝', '铜', '黄金', '稀土'],
            '煤炭': ['煤炭', '煤业', '煤矿', '神华'],
            '钢铁': ['钢铁', '钢', '宝钢', '鞍钢'],
            '运输': ['运输', '物流', '快递', '航运', '航空', '港口', '机场', '海运', '空运'],
            '农业': ['农业', '农', '牧', '渔', '种子', '化肥', '农药', '养殖'],
            '传媒': ['传媒', '文化', '影视', '娱乐', '游戏', '出版', '广告'],
            '旅游': ['旅游', '旅行', '景区', '酒店', '旅行社'],
        }

        for sector, keywords in sector_keywords.items():
            if any(keyword.lower() in name_lower for keyword in keywords):
                sectors.append(sector)

        sectors = list(dict.fromkeys(sectors))
        if not sectors:
            if code.startswith('sh'):
                sectors = ['科创板'] if code[2:].startswith('68') else ['上证主板']
            elif code.startswith('sz'):
                sectors = ['创业板'] if code[2:].startswith('30') else ['深证主板']

        return {
            'sectors': sectors,
            'source': 'inferred',
        }

    def get_sector_hotness(self, sector_name: str) -> int:
        if sector_name in self.sector_hotness:
            return self.sector_hotness[sector_name]
        for sector, hotness in self.sector_hotness.items():
            if sector in sector_name or sector_name in sector:
                return hotness
        return 40

    def get_sector_popularity(self, sector_name: str) -> int:
        if sector_name in self.sector_popularity:
            return self.sector_popularity[sector_name]
        for sector, popularity in self.sector_popularity.items():
            if sector in sector_name or sector_name in sector:
                return popularity
        hotness = self.get_sector_hotness(sector_name)
        return max(30, min(80, int(hotness * 0.8)))

    def analyze_sectors(self, sectors: List[str]) -> Dict:
        if not sectors:
            return {
                'main_sector': '未知',
                'sector_hotness': 40,
                'sector_popularity': 30,
                'sector_category': '其他',
            }

        sector_details = []
        hotness_sum = 0
        popularity_sum = 0

        for sector in sectors:
            hotness = self.get_sector_hotness(sector)
            popularity = self.get_sector_popularity(sector)
            hotness_sum += hotness
            popularity_sum += popularity
            sector_details.append({
                'name': sector,
                'hotness': hotness,
                'popularity': popularity,
            })

        sector_details.sort(key=lambda item: item['hotness'], reverse=True)
        main_sector = sector_details[0]['name']
        category = '其他'
        for cat, cat_sectors in self.sector_categories.items():
            if any(cat_sector in main_sector or main_sector in cat_sector for cat_sector in cat_sectors):
                category = cat
                break

        return {
            'main_sector': main_sector,
            'sector_hotness': hotness_sum // len(sectors),
            'sector_popularity': popularity_sum // len(sectors),
            'sector_category': category,
        }

    def get_stock_sector_info(self, code: str, name: str = '', allow_online: bool = True) -> Dict:
        cached = self.load_from_cache(code)
        if cached:
            return cached

        raw_info = self.fetch_online_sectors(code) if allow_online else None
        if raw_info and raw_info.get('sectors'):
            analysis = self.analyze_sectors(raw_info['sectors'])
            result = {
                'code': code,
                'name': name,
                'sectors': raw_info['sectors'],
                'main_sector': analysis['main_sector'],
                'sector_hotness': analysis['sector_hotness'],
                'sector_popularity': analysis['sector_popularity'],
                'sector_category': analysis['sector_category'],
                'source': raw_info.get('source', '10jqka'),
            }
            self.save_to_cache(code, result)
            return result

        inferred = self.infer_sector_from_name(code, name)
        analysis = self.analyze_sectors(inferred.get('sectors', []))
        return {
            'code': code,
            'name': name,
            'sectors': inferred.get('sectors', []),
            'main_sector': analysis['main_sector'],
            'sector_hotness': analysis['sector_hotness'],
            'sector_popularity': analysis['sector_popularity'],
            'sector_category': analysis['sector_category'],
            'source': inferred.get('source', 'inferred'),
        }


_sector_info_instance = None


def get_sector_info() -> StockSectorInfo:
    global _sector_info_instance
    if _sector_info_instance is None:
        _sector_info_instance = StockSectorInfo()
    return _sector_info_instance
