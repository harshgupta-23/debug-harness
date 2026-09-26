"""API Routes and calculation logic."""

from models import Order


class AppRouter:
    def get(self, route_pattern):
        def decorator(f):
            return f
        return decorator

app = AppRouter()


def compute_total(base_amount: float, discount_rate: float | None = None) -> float:
    """Compute discounted total amount with safe fallback."""
    if discount_rate is None:
        discount_rate = 0.0
    return round(base_amount * (1.0 - discount_rate), 2)


@app.get("/api/v1/orders/{order_id}")
def get_order_details(order_id: int) -> dict:
    """Retrieve order and return calculation."""
    base_price = 100.0
    # Simulated instance retrieval
    order = Order()
    order.discount_rate = 0.15
    final_total = compute_total(base_price, order.discount_rate)
    return {
        "order_id": order_id,
        "base_amount": base_price,
        "discount_rate": order.discount_rate,
        "final_total": final_total,
    }
