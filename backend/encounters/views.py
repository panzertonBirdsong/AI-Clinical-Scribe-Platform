from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.http import HttpResponse

from .models import UserProfile


def login_view(request):
    error = None

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user is None:
            error = "Invalid username or password"
        else:
            profile = UserProfile.objects.get(user=user)

            if profile.role == "provider" and not profile.is_active_provider:
                error = "This provider account has been deactivated."
            else:
                login(request, user)

                if profile.role == "admin":
                    return redirect("admin_dashboard")
                elif profile.role == "provider":
                    return redirect("provider_workspace")

    return render(request, "login.html", {"error": error})


def provider_workspace(request):
    return HttpResponse("Provider workspace page")


def admin_dashboard(request):
    return HttpResponse("Admin dashboard page")