# Stock Stage Trend V7 - 项目总结

## 📊 项目概述
- **项目名称**: Stock Stage Trend V7 (股票阶段趋势分析器)
- **GitHub 仓库**: https://github.com/MaigenLi/stock-stage-trend-v7
- **项目类型**: 股票技术分析工具
- **主要功能**: V7 启动捕捉策略，股票阶段趋势分析

## 🚀 核心功能
### ✅ V7 启动捕捉策略
- 基于技术指标的股票启动信号识别
- 多维度趋势分析
- 智能筛选和排序

### ✅ 本地化数据处理
- 通达信离线数据支持 (.day 文件)
- 本地股票名称数据库
- 板块信息本地推断机制

### ✅ 性能优化
- 并行处理提高扫描速度
- 智能缓存机制
- 只对候选股票进行网络请求

## 📁 项目结构
```
stock_stage_trend/
├── README.md                    # 项目文档
├── requirements.txt             # Python 依赖
├── full_scan_gpt_v7.py          # 主扫描器 (V7策略)
├── stock_names.py               # 股票名称管理
├── stock_sector.py              # 板块信息模块
├── .gitignore                   # Git 忽略规则
├── results/                     # 结果输出目录
├── sector_cache/                # 板块信息缓存
└── __pycache__/                 # Python 缓存
```

## 📈 提交历史 (9次提交)
1. `86c46c4` - Add liquidity filters and strategy presets
2. `ef96e56` - Add hybrid V7 strategy filters
3. `7dfd22c` - Add CSV result export
4. `50ee248` - Refactor local stock name assets
5. `4d3294c` - Fully localize stock metadata logic
6. `e4265d0` - Vendor stock sector module into project
7. `42046e7` - Exclude ST stocks from output
8. `f27906e` - Add project README
9. `ed8f7a5` - Initial commit: V7 scanner with name and sector enrichment

## 🔧 技术栈
- **编程语言**: Python 3
- **数据处理**: pandas, numpy
- **并行处理**: concurrent.futures
- **数据源**: 通达信离线数据
- **网络请求**: requests (用于板块信息)

## 🎯 使用场景
1. **股票筛选**: 快速筛选符合V7策略的股票
2. **趋势分析**: 分析股票阶段趋势和启动信号
3. **投资研究**: 技术指标研究和策略验证
4. **批量处理**: 全市场扫描和结果导出

## 📋 快速开始
```bash
# 克隆仓库
git clone https://github.com/MaigenLi/stock-stage-trend-v7.git

# 安装依赖
pip install -r requirements.txt

# 运行扫描
python full_scan_gpt_v7.py
```

## 🌐 GitHub 信息
- **仓库地址**: https://github.com/MaigenLi/stock-stage-trend-v7
- **克隆命令**:
  ```bash
  git clone https://github.com/MaigenLi/stock-stage-trend-v7.git
  ```
- **SSH 克隆**:
  ```bash
  git clone git@github.com:MaigenLi/stock-stage-trend-v7.git
  ```

## 🔄 与 stock_trend 项目的区别
| 特性 | stock_trend | stock_stage_trend |
|------|-------------|-------------------|
| **策略** | 趋势放量筛选 | V7启动捕捉策略 |
| **数据** | 基础趋势分析 | 阶段趋势分析 |
| **输出** | 简单列表 | CSV导出+详细报告 |
| **优化** | 基本并行 | 智能候选筛选 |

## 📝 注意事项
1. 需要通达信离线数据目录: `~/stock_data/vipdoc/`
2. 股票代码文件: `~/stock_code/results/stock_codes.txt`
3. 首次运行会建立本地缓存
4. 网络请求仅用于补充板块信息

---
*项目推送时间: 2026-03-29 18:44 GMT+8*