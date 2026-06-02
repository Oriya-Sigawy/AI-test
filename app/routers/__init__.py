"""HTTP routers — one module per resource group.

Each router (auth, categories, expenses, budgets, reports) handles HTTP concerns
only: routing, status codes, and dependency injection. Business logic lives in
``app.services``. Routers are added and registered in ``app.main`` per build task.
"""
