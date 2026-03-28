# stock_stage_trend

V7 启动捕捉策略项目。

基于通达信离线日线数据扫描股票，筛选出符合“启动信号”的候选标的，并在输出中附带：
- 股票代码
- 股票名称
- 板块信息
- 板块热度 / 人气
- 简单回测收益

---

## 1. 主要脚本

- `full_scan_gpt_v7.py`：主扫描脚本
- `stock_sector.py`：项目内置板块信息模块（已精简）
- `stock_names.py`：项目内置常见股票名称映射
- `requirements.txt`：Python 依赖列表

---

## 2. 功能说明

当前版本支持：
- 使用通达信离线数据目录：`~/stock_data/vipdoc/`
- 使用股票代码文件：`~/stock_code/results/stock_codes.txt`
- 支持按数量扫描或全量扫描
- 支持多线程并发处理
- 自动排除 `ST` / `*ST` 股票
- 输出候选股票的：
  - 股票名称
  - 主板块
  - 板块分类
  - 板块热度
  - 板块人气
  - 信号评分
  - 回测收益

---

## 3. 名称与板块信息来源

### 股票名称
名称获取顺序：
1. 当前项目本地缓存 `stock_name_cache.json`
2. `stock_names.py` 内置常见股票名称映射
3. 新浪财经接口
4. 东方财富页面回退解析

> 说明：名称缓存现在只使用当前项目自己的 `stock_name_cache.json`，不再读取任何外部项目缓存。

### 板块信息
当前项目已内置本地模块：
- `stock_sector.py`

主脚本只依赖本项目目录下的 `stock_sector.py`，不再依赖任何外部项目实现。
当前 `stock_sector.py` 已做精简，只保留：
- 在线板块抓取
- 本地名称推断
- 热度 / 人气 / 分类计算
- 本项目所需缓存逻辑

> 说明：为了避免全量扫描时产生过多网络请求，脚本只会对“命中候选信号”的股票走网络名称/板块补全；非候选股票只做本地推断或跳过增强信息获取。

---

## 4. 运行环境

建议环境：
- Python 3.10+
- Linux / WSL2

依赖库：
- `numpy`
- `pandas`
- `requests`

推荐直接使用项目内的依赖文件：

```bash
pip install -r requirements.txt
```

---

## 5. 数据与目录约定

脚本内默认使用以下路径：

- 通达信数据目录：`~/stock_data/vipdoc/`
- 股票代码文件：`~/stock_code/results/stock_codes.txt`
- 项目目录：`~/.openclaw/workspace/stock_stage_trend/`
- 结果目录：`~/.openclaw/workspace/stock_stage_trend/results/`
- 板块缓存目录：`~/.openclaw/workspace/stock_stage_trend/sector_cache/`

---

## 6. 使用方法

进入项目目录：

```bash
cd ~/.openclaw/workspace/stock_stage_trend
```

### 6.1 扫描前 N 只股票

```bash
python full_scan_gpt_v7.py --limit 200 --workers 8
```

说明：
- `--limit`：扫描股票数量
- `--workers`：并发线程数

### 6.2 全量扫描

```bash
python full_scan_gpt_v7.py --all --workers 8
```

### 6.3 用 `limit=0` 表示全量

```bash
python full_scan_gpt_v7.py --limit 0 --workers 8
```

---

## 7. 输出说明

运行完成后会在 `results/` 下生成两类文件：

### 详细结果文件
格式类似：

```text
v7_candidates_YYYYMMDD_HHMMSS.txt
```

内容示例：

```text
sh600250 南京商旅
  评分: 8 回测收益: 0.0030
  价格: 12.91 涨跌: +3.53% 三天: +7.05%
  板块: 贸易Ⅱ (其他)
  热度: 40 人气: 32 来源: 10jqka
```

### 代码列表文件
格式类似：

```text
v7_candidates_YYYYMMDD_HHMMSS_codes.txt
```

只包含候选股票代码，方便后续联动其它脚本。

---

## 8. 筛选逻辑概览

脚本核心会做这些判断：
- 趋势抬升
- 最近 3 日上涨
- 突破近 10 日高点
- 成交量放大
- 上涨量能质量优于下跌量能
- K线假突破过滤
- 振幅收敛

最终生成：
- `signal`：是否触发候选信号
- `score`：信号评分
- `backtest_return`：简单回测均值

---

## 9. Git 管理说明

本项目目录已独立初始化为 git 仓库。

默认忽略：
- `results/`
- `sector_cache/`
- `stock_name_cache.json`
- `__pycache__/`

也就是说：
- **源码会进 git**
- **运行结果和缓存不会进 git**

---

## 10. 常见问题

### 结果里股票名称还是显示“未知”
可能原因：
- 本地缓存里没有
- 网络请求失败
- 外部页面结构变化

可先检查：
- 网络是否可用
- `stock_sector.py` 是否存在

### 板块信息来源显示不同
这是正常的，可能来自：
- `10jqka`
- `eastmoney`
- `inferred`

表示脚本用了不同的数据源或回退策略。

---

## 11. 后续可优化方向

- 增加更完整的本地股票名称数据库
- 对板块信息做本地持久化索引
- 增强回测逻辑
- 增加导出 CSV / JSON
- 增加板块统计汇总输出
