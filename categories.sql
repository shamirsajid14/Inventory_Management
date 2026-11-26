BEGIN;

CREATE TABLE IF NOT EXISTS public.categories (
    name VARCHAR(100) NOT NULL CHECK (name <> '' AND name = trim(name)),
    name_key TEXT GENERATED ALWAYS AS (lower(name)) STORED PRIMARY KEY
);

-- Keep category names entered by the CLI, dashboard, or bulk product imports.
CREATE OR REPLACE FUNCTION public.register_product_category()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF trim(NEW.category) <> '' THEN
        INSERT INTO public.categories (name) VALUES (trim(NEW.category))
        ON CONFLICT (name_key) DO NOTHING;

        SELECT name INTO STRICT NEW.category
        FROM public.categories WHERE name_key = lower(trim(NEW.category));
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER register_product_category
    BEFORE INSERT OR UPDATE OF category ON public.products
    FOR EACH ROW EXECUTE FUNCTION public.register_product_category();

INSERT INTO public.categories (name)
SELECT min(trim(category)) FROM public.products
WHERE trim(category) <> ''
GROUP BY lower(trim(category))
ON CONFLICT (name_key) DO NOTHING;

COMMIT;
