from django.urls import path
from . import views

urlpatterns = [
    path("", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("workspace/", views.provider_workspace, name="provider_workspace"),
    path("admin-dashboard/", views.admin_dashboard, name="admin_dashboard"),
    path(
        "<int:encounter_id>/save-raw-input/",
        views.save_raw_input,
        name="save_raw_input",
    ),
    path(
        "<int:encounter_id>/generate-note/",
        views.generate_note,
        name="generate_note",
    ),
    path(
        "<int:encounter_id>/save-note-version/",
        views.save_note_version,
        name="save_note_version",
    )
]