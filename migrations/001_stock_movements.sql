BEGIN;

CREATE TABLE IF NOT EXISTS public.stock_movements (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES public.products(id) ON DELETE RESTRICT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    kind TEXT NOT NULL CHECK (kind IN ('restock', 'removal', 'sale', 'correction')),
    quantity_change NUMERIC(13, 3) NOT NULL CHECK (
        (kind = 'restock' AND quantity_change > 0)
        OR (kind IN ('removal', 'sale') AND quantity_change < 0)
        OR (kind = 'correction' AND quantity_change <> 0)
    ),
    unit TEXT NOT NULL CHECK (unit IN ('kg', 'dozen', 'piece')),
    note VARCHAR(250),
    balance NUMERIC(13, 3) NOT NULL CHECK (balance >= 0),
    sale_id INTEGER UNIQUE REFERENCES public.sales(id) ON DELETE RESTRICT,
    CHECK ((kind = 'sale') = (sale_id IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS stock_movements_product_recent_idx
    ON public.stock_movements (product_id, occurred_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS sales_sold_at_idx ON public.sales (sold_at);

COMMIT;
