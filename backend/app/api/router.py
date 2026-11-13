from fastapi import APIRouter

from app.api.routes import (
    analysis,
    auth,
    clients,
    contracts,
    dashboard,
    health,
    invoices,
    jobs,
    projects,
    tasks,
    users,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(dashboard.router)
api_router.include_router(clients.router)
api_router.include_router(projects.router)
api_router.include_router(tasks.router)
api_router.include_router(contracts.router)
api_router.include_router(jobs.router)
api_router.include_router(invoices.router)
api_router.include_router(analysis.router)
