from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db import transaction
from django.http import JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.http import StreamingHttpResponse, HttpResponseNotAllowed

import json

from .models import UserProfile, Encounter, NoteTemplate, Patient, NoteVersion
from .llm import call_llm



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
                
    else:

        return render(request, "login.html", {"error": error})




@login_required
def provider_workspace(request):
    error = None

    profile = UserProfile.objects.get(user=request.user)

    if profile.role != "provider":
        return redirect("admin_dashboard")

    if not profile.is_active_provider:
        return redirect("login")

    if request.method == "POST":
        
        # visit (modify) an existing encounter
        if request.POST.get("encounter_id"):
            
            encounter_id = request.POST.get("encounter_id")

            encounter = get_object_or_404(
                Encounter.objects.select_related(
                    "provider",
                    "patient",
                ),
                id=encounter_id,
                provider=request.user,
            )

            provider = encounter.provider
            patient = encounter.patient

            note_versions = encounter.versions.all().order_by("-saved_at")
            latest_note_version = note_versions.first()

            note_templates = NoteTemplate.objects.filter(is_active=True).order_by("name")

            return render(request, "encounter.html", {
                "provider": provider,
                "patient": patient,
                "encounter": encounter,
                "note_versions": note_versions,
                "latest_note_version": latest_note_version,
                "note_templates": note_templates,
            })

        # create a new encounter
        else:
            first_name = request.POST.get("first_name")
            last_name = request.POST.get("last_name")
            dob = request.POST.get("dob")

            patient, created = Patient.objects.get_or_create(
                first_name=first_name,
                last_name=last_name,
                date_of_birth=dob,
            )

            encounter = Encounter.objects.create(
                provider=request.user,
                patient=patient,
                status="draft",
            )

            provider = encounter.provider
            patient = encounter.patient

            note_versions = encounter.versions.all().order_by("-saved_at")
            latest_note_version = note_versions.first()

            note_templates = NoteTemplate.objects.filter(is_active=True).order_by("name")

            return render(request, "encounter.html", {
                "provider": provider,
                "patient": patient,
                "encounter": encounter,
                "note_versions": note_versions,
                "latest_note_version": latest_note_version,
                "note_templates": note_templates,
            })


    else:

        provider_encounters = Encounter.objects.filter(
            provider=request.user
        ).select_related(
            "patient",
        ).order_by("-updated_at")

        return render(request, "provider_workspace.html", {
            "error": error,
            "provider_encounters": provider_encounters,
        })
    

@login_required
def save_raw_input(request, encounter_id):
    encounter = get_object_or_404(
        Encounter.objects.select_related(
            "provider",
            "patient",
        ),
        id=encounter_id,
        provider=request.user,
    )

    if request.method == "POST":
        raw_text = request.POST.get("raw_text", "")

        encounter.raw_input = raw_text
        encounter.save()

    provider = encounter.provider
    patient = encounter.patient

    note_versions = encounter.versions.all().order_by("-saved_at")
    latest_note_version = note_versions.first()

    note_templates = NoteTemplate.objects.filter(is_active=True).order_by("name")

    return render(request, "encounter.html", {
        "provider": provider,
        "patient": patient,
        "encounter": encounter,
        "note_versions": note_versions,
        "latest_note_version": latest_note_version,
        "note_templates": note_templates,
    })


@login_required
def generate_note(request, encounter_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    encounter = get_object_or_404(
        Encounter.objects.select_related(
            "provider",
            "patient",
        ),
        id=encounter_id,
        provider=request.user,
    )

    template_id = request.POST.get("template_id")

    def stream_response():
        try:
            for chunk in call_llm(encounter.id, template_id):
                data = json.dumps({
                    "delta": chunk,
                })

                yield f"data: {data}\n\n"

            yield "event: done\ndata: {}\n\n"

        except Exception as e:
            error_data = json.dumps({
                "error": str(e),
            })

            yield f"event: error\ndata: {error_data}\n\n"

    response = StreamingHttpResponse(
        stream_response(),
        content_type="text/event-stream",
    )

    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"

    return response


@login_required
@require_POST
def save_note_version(request, encounter_id):
    encounter = get_object_or_404(
        Encounter.objects.select_related(
            "provider",
            "patient",
        ),
        id=encounter_id,
        provider=request.user,
    )


    note_text = request.POST.get("note_text", "")

    with transaction.atomic():
        # Get latest version first
        latest_version = (
            encounter.versions
            .order_by("-version_number")
            .first()
        )

        # Delete older draft notes.
        # After this, only the latest draft is allowed to remain.
        if latest_version:
            encounter.versions.filter(
                status="draft"
            ).exclude(
                id=latest_version.id
            ).delete()


        # Re-fetch latest version after cleanup
        latest_version = (
            encounter.versions
            .order_by("-version_number")
            .first()
        )

        if latest_version and latest_version.status == "draft":
            # Latest note is an unsaved draft.
            # Manual save should overwrite it and finalize it.
            latest_version.note_text = note_text
            latest_version.status = "finalized"
            latest_version.saved_by = request.user
            latest_version.save(
                update_fields=[
                    "note_text",
                    "status",
                    "saved_by",
                    "saved_at",
                ]
            )
        else:
            # Latest note is finalized, or there are no previous versions.
            # Create a new finalized version.
            if latest_version:
                next_version_number = latest_version.version_number + 1
            else:
                next_version_number = 1

            NoteVersion.objects.create(
                encounter=encounter,
                version_number=next_version_number,
                note_text=note_text,
                status="finalized",
                saved_by=request.user,
            )

        encounter.status = "finalized"
        encounter.save(update_fields=["status", "updated_at"])


    note_versions = encounter.versions.all().order_by("-saved_at")
    latest_note_version = note_versions.first()
    note_templates = NoteTemplate.objects.filter(is_active=True).order_by("name")

    return render(request, "encounter.html", {
        "provider": encounter.provider,
        "patient": encounter.patient,
        "encounter": encounter,
        "note_versions": note_versions,
        "latest_note_version": latest_note_version,
        "note_templates": note_templates,
    })


@login_required
@require_POST
def autosave_note_draft(request, encounter_id):
    encounter = get_object_or_404(
        Encounter.objects.select_related(
            "provider",
            "patient",
        ),
        id=encounter_id,
        provider=request.user,
    )

    note_text = request.POST.get("note_text", "")

    with transaction.atomic():
        latest_version = (
            encounter.versions
            .order_by("-version_number")
            .first()
        )

        if latest_version and latest_version.status == "draft":
            # Latest version is already a draft.
            # Autosave only updates the text.
            latest_version.note_text = note_text
            latest_version.saved_by = request.user
            latest_version.save(
                update_fields=[
                    "note_text",
                    "saved_by",
                    "saved_at",
                ]
            )

            draft_version = latest_version

        else:
            # Latest version is finalized, or there is no version yet.
            # Autosave creates a new draft.
            if latest_version:
                next_version_number = latest_version.version_number + 1
            else:
                next_version_number = 1

            draft_version = NoteVersion.objects.create(
                encounter=encounter,
                version_number=next_version_number,
                note_text=note_text,
                status="draft",
                saved_by=request.user,
            )

        # the encounter itself is still in draft mode while autosaving.
        encounter.status = "draft"
        encounter.save(update_fields=["status", "updated_at"])

    return JsonResponse({
        "ok": True,
        "version_number": draft_version.version_number,
        "status": draft_version.status,
        "saved_at": draft_version.saved_at.strftime("%Y-%m-%d %H:%M:%S"),
    })




@login_required
def admin_dashboard(request):
    return HttpResponse("Admin dashboard page")





def logout_view(request):
    return HttpResponse("logout")