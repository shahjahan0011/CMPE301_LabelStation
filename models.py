class ProductionOrder:
    def __init__(self, order_id, product_name, planned_quantity,
                 planned_production_time, ideal_cycle_time, status):
        self.order_id = order_id
        self.product_name = product_name
        self.planned_quantity = planned_quantity
        self.planned_production_time = planned_production_time
        self.ideal_cycle_time = ideal_cycle_time
        self.status = status


class OEERecord:
    def __init__(self, order_id, runtime, total_count, good_count,
                 availability, performance, quality, oee):
        self.order_id = order_id
        self.runtime = runtime
        self.total_count = total_count
        self.good_count = good_count
        self.availability = availability
        self.performance = performance
        self.quality = quality
        self.oee = oee