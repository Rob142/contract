from fastapi import APIRouter

from app.api.routes import (
    analysis,
    attachments,
    auth,
    clients,
    contracts,
    dashboard,
    health,
    invoices,
    jobs,
    portfolio,
    projects,
    public,
    settlement,
    sharing,
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
api_router.include_router(attachments.router)
api_router.include_router(sharing.router)
api_router.include_router(public.router)
api_router.include_router(portfolio.router)
api_router.include_router(portfolio.public_router)
api_router.include_router(settlement.router)
