BEGIN;

ALTER TABLE public.sales
    ALTER COLUMN quantity TYPE NUMERIC(13, 3),
    ADD COLUMN IF NOT EXISTS request_id UUID;

CREATE UNIQUE INDEX IF NOT EXISTS sales_request_id_key
    ON public.sales (request_id) WHERE request_id IS NOT NULL;

COMMIT;
