"""Database ORM models for mock workspace."""

class Base:
    pass

class Column:
    def __init__(self, col_type, nullable=True, default=None):
        self.col_type = col_type
        self.nullable = nullable
        self.default = default

class Integer:
    pass

class Float:
    pass

class String:
    pass


class Order(Base):
    """Order database model mapping to 'orders' table."""
    __tablename__ = "orders"

    id = Column(Integer, nullable=False)
    total_amount = Column(Float, nullable=False)
    discount_rate = Column(Float, nullable=True)  # Nullable column causing runtime drift
