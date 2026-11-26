from decimal import Decimal

import models


MAX_INTEGER = 2_147_483_647
MAX_TEXT_LENGTH = 100


def read_integer(prompt, minimum=0):
    while True:
        try:
            value = int(input(prompt))
            if minimum <= value <= MAX_INTEGER:
                return value
        except ValueError:
            pass
        print(f"Enter a whole number from {minimum:,} to {MAX_INTEGER:,}.")


def read_price():
    while True:
        try:
            return models.decimal_value(
                input("Enter product price: "), "Price", "price", models.MAX_PRICE,
                Decimal("0.01"), "Price allows up to two decimal places.",
            )
        except models.InventoryError as error:
            print(error)


def read_text(prompt, required=False):
    while True:
        value = input(prompt).strip()
        if required and not value:
            print("Product name is required.")
        elif len(value) > MAX_TEXT_LENGTH:
            print(f"Enter no more than {MAX_TEXT_LENGTH} characters.")
        else:
            return value


def read_unit():
    while True:
        unit = input("Stock unit (kg, dozen, piece) [piece]: ").strip().lower() or "piece"
        if unit in models.UNIT_STEPS:
            return unit
        print("Choose kg, dozen, or piece.")


def read_stock(prompt, unit, field, *, positive=False):
    while True:
        try:
            return models.stock_amount(input(prompt), unit, field, positive=positive)
        except models.InventoryError as error:
            print(error)


def read_product_category():
    categories = models.get_product_categories()
    if categories:
        print("\nExisting categories")
        for category in categories:
            print(f"  {category}")

    entered_category = read_text("Enter category name (existing or new, optional): ")
    for category in categories:
        if category.lower() == entered_category.lower():
            return category
    return entered_category


def read_product_details(unit=None):
    name = read_text("Enter product name: ", required=True)
    price = read_price()
    adding = unit is None
    if adding:
        unit = read_unit()
    quantity = read_stock(f"Enter product quantity ({unit}): ", unit, "quantity")
    minimum = read_stock(f"Enter minimum stock ({unit}): ", unit, "min_stock")
    category = read_product_category() if adding else read_text("Enter category: ")
    return (name, price, quantity, minimum, category), unit


def main():
    while True:
        print("\nInventory Management System")
        print("1. Add product")
        print("C. Add category")
        print("2. View products")
        print("3. Update product")
        print("4. Add Stock")
        print("5. Remove Stock")
        print("6. Delete product")
        print("7. Record Sale")
        print("H. Stock History")
        print("8. Exit")

        choice = input("Enter your choice: ").strip().lower()
        try:
            match choice:
                case "1":
                    details, unit = read_product_details()
                    product = models.add_product(*details, unit=unit)
                    print("Product added successfully.")
                    print("Product ID is", product.id)
                case "c":
                    name, created = models.add_category(read_text("Enter category name: "))
                    print(f'Category "{name}" added.' if created else f'Category "{name}" already exists.')
                case "2":
                    print("View Products")
                    for product in models.get_products():
                        print(product)
                case "3":
                    product_id = read_integer("Enter product ID: ", minimum=1)
                    unit = models.get_product(product_id).unit
                    details, _ = read_product_details(unit)
                    models.update_product(*details, product_id=product_id)
                    print("Updated successfully.")
                case "4" | "5" | "7":
                    product_id = read_integer("Enter product ID: ", minimum=1)
                    unit = models.get_product(product_id).unit
                    label = {"4": "stock amount", "5": "quantity to remove", "7": "quantity sold"}[choice]
                    amount = read_stock(f"Enter {label} ({unit}): ", unit, "amount", positive=True)
                    if choice == "7":
                        sale = models.record_sale(product_id, amount)
                        print(
                            f"Sold {models.quantity_label(amount, unit)} of {sale.product.name}. "
                            f"Total price: Rs {sale.total:,.2f}."
                        )
                        remaining = models.quantity_label(sale.product.quantity, unit)
                    else:
                        handler = models.add_stock if choice == "4" else models.remove_stock
                        product = handler(product_id, amount, note="Manual CLI adjustment.")
                        verb = "Added" if choice == "4" else "Removed"
                        print(f"{verb} {models.quantity_label(amount, unit)} of {product.name}.")
                        remaining = models.quantity_label(product.quantity, unit)
                    print(f"Stock remaining: {remaining}.")
                case "6":
                    product_id = read_integer("Enter product ID: ", minimum=1)
                    models.delete_product(product_id)
                    print("Product deleted successfully.")
                case "h":
                    product_id = read_integer("Enter product ID: ", minimum=1)
                    product = models.get_product(product_id)
                    print(f"Stock history for {product.name} (Pakistan time)")
                    history = models.get_stock_history(product_id)
                    if not history:
                        print("No stock movements recorded yet.")
                    for occurred, kind, change, unit, note, balance in history:
                        signed = ("+" if change > 0 else "−") + models.quantity_label(abs(change), unit)
                        print(f"{occurred:%Y-%m-%d %H:%M:%S} | {kind.title()} | {signed} | Balance {models.quantity_label(balance, unit)} | {note or '—'}")
                case "8":
                    print("Exiting system.")
                    return
                case _:
                    print("Choose a number from 1 to 8, C for categories, or H for stock history.")
        except models.InventoryError as error:
            print(error)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Exiting system.")
        raise SystemExit(130) from None
