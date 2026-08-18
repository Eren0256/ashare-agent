from ..state import AgentState
from ..models import TaskSpec
from ._utils import dumps


class UnderstandNode:
    def __init__(self, model):
        self._model = model.with_structured_output(TaskSpec)

    async def __call__(
        self,
        state: AgentState,
    ) -> dict:

        question = state["question"]
        conversation_context = state.get(
            "conversation_context",
            [],
        )

        prompt = f"""
你是中国A股分析 Agent 的问题理解模块。

你的任务不是回答问题，而是把用户问题转换成 TaskSpec。

规则：

1. 如果问题属于中国A股、上市公司、财务、估值、行情、
   公司业务、行业、股东、分红等相关分析，
   domain = "a_share"

2. 如果明显不属于中国A股分析范围，
   domain = "out_of_scope"

3. intent 使用简短稳定的英文 snake_case 描述用户目的。

例如：

主营业务 -> company_business
公司信息 -> company_profile
营业收入、净利润、资产、负债、现金流 -> financial_statement
ROE、资产负债率等计算指标 -> financial_indicator
近N年财务数据、同比、增长率、CAGR、增长趋势 -> financial_analysis
财务报表 -> financial_statement

4. entities 只提取用户问题中明确出现的公司、
股票、指数、行业等对象。

5. year 和 quarter 只提取用户明确指定的财务报告期。
例如“2025年”对应 year=2025、quarter=null；
“2025年第三季度”对应 year=2025、quarter=3；
用户只说“最新”时两者都为 null。

6. financial_metrics 只提取用户明确询问的基础财务指标，不得扩展：

营业收入 -> revenue
营业总收入、总收入 -> total_revenue
营业成本 -> operating_cost
营业利润 -> operating_profit
利润总额 -> total_profit
净利润 -> net_profit
归母净利润 -> parent_net_profit
基本每股收益 -> basic_eps
货币资金 -> cash
应收账款 -> accounts_receivable
存货 -> inventory
流动资产 -> current_assets
总资产 -> total_assets
流动负债 -> current_liabilities
总负债 -> total_liabilities
归母股东权益 -> parent_equity
所有者权益 -> total_equity
经营、投资、筹资活动现金流量净额分别对应
operating_cash_flow、investing_cash_flow、financing_cash_flow
现金及现金等价物净增加额 -> net_cash_increase
期末现金及现金等价物余额 -> ending_cash_equivalents

如果不是查询这些基础财务指标，financial_metrics 为空列表。

7. 对 financial_analysis：

- lookback_years 提取用户明确要求的年度数量，例如“近5年”填5；
  用户只说“近年来”时默认填5。
- 用户指定“截至2024年”时 year=2024；没有指定截止年时 year=null。
- financial_analyses 只根据问题填写：
  只问近N年数值 -> [values]
  问每年同比、逐年增速 -> [yoy]
  问复合增长率、CAGR、年均增速 -> [cagr]
  笼统询问“增长率” -> [yoy, cagr]
  问增长趋势、变化趋势 -> [trend]

financial_analysis 目前只分析完整年度报告，不分析季度序列，也不预测未来。

8. output_modes 默认包含 text。只有用户明确要求绘图、画图、图表、
走势图或可视化时才同时包含 chart。

9. 历史对话只用于理解当前问题中省略的公司、指标和时间等指代。
当前问题中的明确要求优先，不得把历史中无关的对象带入当前任务。

历史对话：

{dumps(conversation_context)}

当前用户问题：

{question}
"""

        task = await self._model.ainvoke(prompt)

        task.output_modes = list(dict.fromkeys(task.output_modes))

        return {"task": task}
