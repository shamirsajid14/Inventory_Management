import csv
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qsl, urlencode
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import models
from reports import build_report, report_dates


ROOT = Path(__file__).resolve().parent
app = FastAPI(title="Inventory Admin")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")
templates.env.filters["quantity"] = models.quantity_label
templates.env.filters["money"] = lambda amount: f"Rs {amount:,.2f}"

SECTIONS = {"/admin": "Dashboard", "/admin/products": "Products", "/admin/stock": "Stock"}
SORT_LABELS = {
    "name": "Name A–Z", "id": "Product ID", "newest": "Newest first", "price-high": "Price high to low",
    "price-low": "Price low to high", "stock-low": "Lowest stock",
}
ACTION_LABELS = {
    "new": "Add product", "add-category": "Add category", "view": "Product details", "edit": "Edit product",
    "add-stock": "Add stock", "remove-stock": "Remove stock", "sale": "Record sale",
    "delete": "Delete product", "history": "Stock History", "restock": "Restock",
}


def page_number(raw):
    return max(1, int(raw)) if raw and raw.isascii() and raw.isdecimal() and len(raw) < 10 else 1


@dataclass(frozen=True)
class ProductFilters:
    path: str
    search: str
    category: str
    unit: str
    low: bool
    sort: str
    page: int

    @classmethod
    def from_request(cls, request):
        query = request.query_params
        unit, sort = query.get("unit", ""), query.get("sort", "")
        return cls(
            request.url.path, query.get("q", "").strip()[:100],
            query.get("category", "").strip()[:100], unit if unit in models.UNIT_STEPS else "",
            query.get("low") == "1", sort if sort in models.SORTS else "name",
            page_number(query.get("page")),
        )

    def url(self, **updates):
        params = {
            "q": self.search, "category": self.category, "unit": self.unit,
            "low": "1" if self.low else "", "sort": self.sort if self.sort != "name" else "",
            "page": self.page,
        }
        params.update(updates)
        if params["page"] == 1:
            del params["page"]
        query = urlencode({key: value for key, value in params.items() if value})
        return f"{self.path}?{query}" if query else self.path


def render(request, template, context, status=200):
    return templates.TemplateResponse(
        request=request, name=template, context=context, status_code=status,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/")
def home():
    return RedirectResponse(url="/admin")


@app.get("/api/products")
def list_products():
    products = [
        {
            "id": product_id, "name": name, "price": f"{price:.2f}", "quantity": quantity,
            "min_stock": minimum, "category": category, "unit": unit,
        }
        for product_id, name, price, quantity, minimum, category, unit in models.get_products()
    ]
    return {"Total": len(products), "Products": products}


def action_from_request(request):
    action = request.query_params.get("action")
    if action not in ACTION_LABELS:
        raise HTTPException(404, "Inventory action not found.")
    if action in {"new", "add-category"}:
        return action, None
    raw = request.query_params.get("id", "")
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 10 or not 1 <= int(raw) <= 2_147_483_647:
        raise HTTPException(404, "Product not found.")
    return action, int(raw)


def product_context(request, filters):
    return {
        "section": SECTIONS[filters.path], "filters": filters,
        "categories": models.get_product_categories(), "unit_steps": models.UNIT_STEPS,
        "sort_labels": SORT_LABELS, "notice": request.query_params.get("notice", "")[:250],
    }


def render_products(request, filters, context, status=200):
    context["results"] = models.get_product_page(
        search=filters.search, category=filters.category, unit=filters.unit,
        low=filters.low, sort=filters.sort, page=filters.page,
    )
    if filters.path == "/admin":
        context["summary"] = models.inventory_summary()
    return render(request, "products.html", context, status)


def render_action(request, filters, action, product_id, entries=None, error=None, *, category_notice=None):
    product = None
    if product_id is not None:
        try:
            product = models.get_product(product_id)
        except models.InventoryError as missing:
            error = missing
    if entries is None:
        entries = {
            "name": product.name, "price": format(product.price, ".2f"),
            "min_stock": format(product.min_stock, "f"), "category": product.category or "",
            "unit": product.unit,
        } if product else {"quantity": "0", "min_stock": "0", "unit": "piece"}
    if action == "sale":
        entries.setdefault("request_id", str(uuid4()))
    if action == "restock" and product and product.restock_amount:
        entries.setdefault("amount", format(product.restock_amount, "f"))
    context = product_context(request, filters)
    if action == "history" and product:
        context["movements"] = models.get_stock_history(product.id)
    context.update(
        action=action, action_label=ACTION_LABELS[action], product=product, entries=entries, error=error,
        action_url=filters.url(action=action, id=product_id), return_url=filters.url(),
        category_notice=category_notice,
    )
    status = error.status if error else 200
    if request.headers.get("X-Inventory-Panel") == "1":
        return render(request, "product_panel.html", context, status)
    return render_products(request, filters, context, status)


@app.get("/admin", response_class=HTMLResponse)
@app.get("/admin/products", response_class=HTMLResponse)
@app.get("/admin/stock", response_class=HTMLResponse)
def products_page(request: Request):
    filters = ProductFilters.from_request(request)
    if "action" in request.query_params:
        return render_action(request, filters, *action_from_request(request))
    return render_products(request, filters, product_context(request, filters))


async def read_form(request: Request):
    origin = request.headers.get("origin")
    expected_origin = f"{request.url.scheme}://{request.url.netloc}"
    if request.headers.get("sec-fetch-site") == "cross-site" or (origin and origin != expected_origin):
        raise HTTPException(403, "Open the action from the inventory dashboard.")
    if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Submit the inventory form from the dashboard.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 8192:
            raise HTTPException(413, "The submitted form is too large.")
    try:
        return dict(parse_qsl(body.decode(), keep_blank_values=True, max_num_fields=12))
    except (UnicodeError, ValueError):
        raise HTTPException(400, "The submitted form could not be read.") from None


def apply_action(action, product_id, entries):
    if action == "add-category":
        name, created = models.add_category(entries.get("category", ""))
        entries["category"] = name
        return f'Category "{name}" added.' if created else f'Category "{name}" already exists.'

    if action in {"new", "edit"}:
        details = (
            entries.get("name", ""), entries.get("price", ""),
            entries.get("quantity", "") if action == "new" else None,
            entries.get("min_stock", ""), entries.get("category", ""),
        )
        if action == "new":
            product = models.add_product(*details, unit=entries.get("unit", ""))
            return f"{product.name} added."
        product = models.update_product(*details, product_id=product_id)
        return f"{product.name} updated."

    if action == "delete":
        product = models.delete_product(product_id)
        return f"{product.name} deleted."

    amount = entries.get("amount", "")
    if action == "sale":
        try:
            token = UUID(entries.get("request_id", ""))
        except ValueError:
            entries["request_id"] = str(uuid4())
            raise models.InventoryError("Sale form refreshed. Review the amount and submit again.") from None
        sale = models.record_sale(product_id, amount, token)
        verb = "Sale already recorded" if sale.replayed else "Sale recorded"
        return f"{verb} for {sale.product.name}. Rs {sale.total:,.2f}."

    handler, verb = (
        (models.add_stock, "Added stock") if action in {"add-stock", "restock"}
        else (models.remove_stock, "Removed stock")
    )
    product = handler(product_id, amount, note=entries.get("note"))
    return f"{verb} for {product.name}. {models.quantity_label(product.quantity, product.unit)} on hand."


@app.post("/admin", response_class=HTMLResponse)
@app.post("/admin/products", response_class=HTMLResponse)
@app.post("/admin/stock", response_class=HTMLResponse)
def product_action(request: Request, entries: dict = Depends(read_form)):
    filters = ProductFilters.from_request(request)
    action, product_id = action_from_request(request)
    if action in {"view", "history"}:
        raise HTTPException(405)
    inline_category = action == "new" and entries.get("intent") == "add-category"
    try:
        notice = apply_action("add-category" if inline_category else action, product_id, entries)
    except models.InventoryError as error:
        return render_action(request, filters, action, product_id, entries, error)
    if inline_category:
        return render_action(request, filters, action, product_id, entries, category_notice=notice)
    return RedirectResponse(filters.url(notice=notice), status_code=303)


@app.get("/admin/sales", response_class=HTMLResponse)
def sales_page(request: Request):
    summary, results = models.get_sales_page(page_number(request.query_params.get("page")))
    return render(request, "sales.html", {"section": "Sales", "summary": summary, "results": results})


@app.get("/admin/sales/reports", response_class=HTMLResponse)
def sales_report(request: Request, start: str = "", end: str = ""):
    try:
        first, last = report_dates(start, end)
    except ValueError as error:
        return render(request, "sales_report.html", {
            "section": "Sales", "start": start, "end": end, "report_error": str(error),
        }, 422)
    daily, top, total = build_report(first, last)
    return render(request, "sales_report.html", {
        "section": "Sales", "start": first, "end": last, "daily": daily, "top": top, "total": total,
        "export_url": "/admin/sales/reports.csv?" + urlencode({"start": first, "end": last}),
    })


@app.get("/admin/sales/reports.csv")
def export_sales_report(start: str = "", end: str = ""):
    try:
        first, last = report_dates(start, end)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    daily, _, total = build_report(first, last)
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "Date (Pakistan time)", "Sales", "Known revenue (PKR)", "Kg sold",
        "Dozen sold", "Pieces sold", "Sales without price",
    ])
    for label, summary in [*daily.items(), ("Total", total)]:
        writer.writerow([
            label, summary.sales, f"{summary.revenue:.2f}", *summary.quantities.values(), summary.missing,
        ])
    return Response(
        output.getvalue().encode("utf-8-sig"), media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="sales-{first}-to-{last}.csv"',
            "Cache-Control": "no-store",
        },
    )
