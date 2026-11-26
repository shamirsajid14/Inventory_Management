# Inventory Management System

A Python and PostgreSQL inventory project for a grocery store. Manage products, stock, and sales from the FastAPI dashboard or the command-line menu. Prices are in Pakistani rupees (PKR).

## Requirements

- Python 3.10 or later
- A running PostgreSQL server

From the project folder in PowerShell, install the Python dependencies.

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

## Set up PostgreSQL

Edit `.env` with your PostgreSQL connection details. The example uses `localhost:5432`, the `inventory_db` database, and the `postgres` role. Set `PGPASSWORD` to your local PostgreSQL password.

For a new installation, create `inventory_db` in pgAdmin or use these commands in PowerShell with the PostgreSQL command-line tools on your `PATH`.

```powershell
createdb -h localhost -p 5432 -U postgres inventory_db
```

Load the base schema into an empty database from PowerShell.

```powershell
psql -h localhost -p 5432 -U postgres -d inventory_db -v ON_ERROR_STOP=1 -f schema.sql
```

For existing installations with the `products.unit` column, apply [sales_dashboard.sql](sales_dashboard.sql) if the database still needs decimal sales quantities or sale retry keys. Fresh installations already have these in the base schema.

```powershell
psql -h localhost -p 5432 -U postgres -d inventory_db -v ON_ERROR_STOP=1 -f sales_dashboard.sql
```

For both new and existing installations, run the category migration after creating the products table. It imports existing category names and makes categories available before their first product is added.

```powershell
psql -h localhost -p 5432 -U postgres -d inventory_db -v ON_ERROR_STOP=1 -f categories.sql
psql -h localhost -p 5432 -U postgres -d inventory_db -v ON_ERROR_STOP=1 -f migrations/001_stock_movements.sql
```

The stock movement migration starts history from installation. Earlier sales remain in Sales history and Sales Reports.

## Load sample inventory (optional)

Use the following command if your checkout includes `seed_inventory.py`.

```powershell
python seed_inventory.py
```

The seed script adds 200 Pakistani grocery products across 10 categories, with 20 products per category and a few low-stock items. Product names include selling units, such as `Masoor dal (500 g)`. A quantity of `30` for that product means 30 packets, and minimum stock uses the same unit.

The script matches products by full name and category, ignoring capitalization and surrounding spaces. It skips existing matches and reports the inserted, existing, and verified counts for each category.

## Run the command-line menu

```powershell
python main.py
```

| Option | Action |
| --- | --- |
| 1 | Add a product with a price, quantity, minimum stock, and optional category |
| C | Add a category |
| 2 | View products and their IDs |
| 3 | Update a product by ID |
| 4 | Add stock by product ID |
| 5 | Remove stock by product ID |
| 6 | Delete a product that has no recorded sales |
| 7 | Record a sale by product ID and quantity |
| H | View a product’s stock movement history |
| 8 | Exit |

When adding a product, enter the price as a number such as `190.00` and choose a stock unit. Kilograms allow three decimal places, dozens allow whole and half values, and pieces must be whole. At the category prompt, type an existing category name, enter a new one, or leave it blank.

The sale option saves the current unit price and deducts the quantity in one transaction. It accepts a positive quantity up to the available stock.

## Run the web dashboard

In a separate PowerShell window from the project folder, start the development server.

```powershell
python -m uvicorn admin_app:app --host 127.0.0.1 --port 8000 --reload
```

| Address | What it shows |
| --- | --- |
| [/admin](http://127.0.0.1:8000/admin) | Inventory totals, low-stock shortcut, and product tools |
| [/admin/products](http://127.0.0.1:8000/admin/products) | Search, filter, sort, and manage products |
| [/admin/stock](http://127.0.0.1:8000/admin/stock) | Stock levels and adjustment forms |
| [/admin/sales](http://127.0.0.1:8000/admin/sales) | Sale history, quantities, and revenue in PKR |
| [/admin/sales/reports](http://127.0.0.1:8000/admin/sales/reports) | Daily revenue, top products, and a CSV export for the selected Pakistan-time dates |
| [/api/products](http://127.0.0.1:8000/api/products) | JSON with `Total` and `Products`. Prices are strings with two decimal places |
| [/docs](http://127.0.0.1:8000/docs) | Interactive API documentation |

From a product row, choose **Manage** to see details and open stock, sale, or deletion forms. Change stock through **Add stock**, **Remove stock**, or **Record sale**. The edit form shows the stock unit and current quantity for reference.

Choose **Add category** beside **Add product** to save a category on its own. In the **Add product** form, you can also enter a category name and choose **Add category** to save it and keep filling in the product. Both the dashboard and CLI reuse existing names regardless of capitalization or surrounding spaces.

Choose **Manage**, then **Stock History**, to see signed movements, notes, and the stock balance after each change. The **Low stock** filter opens the restock queue. Its **Restock** action starts with the amount needed to reach minimum stock.

## Run integration tests

Configure `.env` as above and use a PostgreSQL role with permission to create a database. The tests create and remove a uniquely named `inventory_test_*` database using the base schema and migrations. FastAPI’s test client runs requests in-process.

```powershell
python -B -m pytest -p no:cacheprovider
```

## Project files

| File | Purpose |
| --- | --- |
| [main.py](main.py) | Command-line prompts and menu |
| [models.py](models.py) | PostgreSQL queries for products, stock, and sales |
| [database.py](database.py) | PostgreSQL connection helper |
| [admin_app.py](admin_app.py) | FastAPI app and product routes |
| [templates](templates/) | Jinja2 pages and product action forms |
| [static](static/) | Dashboard styles and interactions |
| [sales_dashboard.sql](sales_dashboard.sql) | Existing database migration for decimal sales and safe sale retries |
| [categories.sql](categories.sql) | Shared category list and registration of categories entered on products |
| [schema.sql](schema.sql) | Base schema for fresh installations |
| [migrations/001_stock_movements.sql](migrations/001_stock_movements.sql) | Stock movement history and sale-date index |
| [tests](tests/) | PostgreSQL integration suite |
| [product_constraints.sql](product_constraints.sql) | Adds the price and stock checks to an existing `products` table that lacks them |
