from django.urls import path
from . import views

urlpatterns = [
    path("", views.login_view, name="login"),
    # path("logout/", views.logout_view, name="logout"),
    path("workspace/", views.provider_workspace, name="provider_workspace"),
    path("admin-dashboard/", views.admin_dashboard, name="admin_dashboard"),
]