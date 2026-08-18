from pydantic import BaseModel

from .security import Security


class CompanyBusiness(BaseModel):
    security: Security
    main_business: str
    product_types: str
    products: str
    business_scope: str


# 数据结构参考 AKShare 返回的结构：
# [
#     {
#         "股票代码": "600519",
#         "主营业务": "茅台酒及系列酒的生产与销售。",
#         "产品类型": "茅台酒、其他系列酒",
#         "产品名称": "茅台酒、其他系列酒",
#         "经营范围": "茅台酒及系列酒的生产与销售；饮料、食品、包装材料的生产、销售；防伪技术开发、信息产业相关产品的研制、开发；酒店经营管理、住宿、餐饮、娱乐、洗浴及停车场管理服务；车辆运输（不含危险化学品）、维修保养；第二类增值电信业务。",
#     }
# ]
