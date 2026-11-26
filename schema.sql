CREATE TABLE public.products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    price NUMERIC(10, 2) NOT NULL,
    quantity NUMERIC(13, 3) NOT NULL DEFAULT 0,
    min_stock NUMERIC(13, 3) NOT NULL DEFAULT 5,
    category VARCHAR(100),
    unit TEXT NOT NULL DEFAULT 'piece' CHECK (unit IN ('kg', 'dozen', 'piece')),
    CONSTRAINT products_price_nonnegative_finite
        CHECK (price >= 0 AND price < 'Infinity'::numeric),
    CONSTRAINT products_quantity_nonnegative CHECK (quantity >= 0),
    CONSTRAINT products_min_stock_nonnegative CHECK (min_stock >= 0),
    CONSTRAINT products_piece_whole_stock CHECK (
        unit <> 'piece' OR (quantity = trunc(quantity) AND min_stock = trunc(min_stock))
    ),
    CONSTRAINT products_dozen_half_stock CHECK (
        unit <> 'dozen' OR (mod(quantity, 0.5) = 0 AND mod(min_stock, 0.5) = 0)
    )
);

CREATE TABLE public.sales (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES public.products(id),
    quantity NUMERIC(13, 3) NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC NOT NULL CHECK (unit_price >= 0),
    sold_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    request_id UUID
);

CREATE UNIQUE INDEX sales_request_id_key ON public.sales (request_id) WHERE request_id IS NOT NULL;
