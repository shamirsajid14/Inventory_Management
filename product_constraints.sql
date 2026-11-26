ALTER TABLE public.products
    ADD CONSTRAINT products_price_nonnegative_finite
        CHECK (price >= 0 AND price < 'Infinity'::numeric),
    ADD CONSTRAINT products_quantity_nonnegative CHECK (quantity >= 0),
    ADD CONSTRAINT products_min_stock_nonnegative CHECK (min_stock >= 0);
