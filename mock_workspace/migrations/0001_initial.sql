-- Initial schema migration for orders table
CREATE TABLE orders (
    id INT PRIMARY KEY,
    total_amount FLOAT NOT NULL,
    discount_rate FLOAT
);
