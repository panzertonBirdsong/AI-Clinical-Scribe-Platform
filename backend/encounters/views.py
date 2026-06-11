from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db import transaction
from django.http import JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.http import StreamingHttpResponse, HttpResponseNotAllowed
from django.contrib.auth.models import User

import json

from .models import UserProfile, Encounter, NoteTemplate, Patient, NoteVersion
from .llm import call_llm, search_code



def login_view(request):
    error = None

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(
            request,
            username=username,
            password=password,
        )

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
                    error = "Invalid user role."

    return render(request, "login.html", {
        "error": error,
    })



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



@require_POST
def icd10_search(request):
    user_input = request.POST.get("user_input", "").strip()

    if not user_input:
        return JsonResponse({
            "success": False,
            "codes": [],
            "error": "Empty search input"
        })

    try:
        codes = search_code(user_input)

        return JsonResponse({
            "success": True,
            "codes": codes
        })

    except Exception as e:
        return JsonResponse({
            "success": False,
            "codes": [],
            "error": str(e)
        }, status=500)


@login_required
def admin_dashboard(request):
    from django.urls import reverse

    error = None
    valid_sections = {"encounters", "providers", "templates"}

    def normalize_section(section):
        if section in valid_sections:
            return section
        return "encounters"

    active_section = normalize_section(
        request.POST.get("active_section") or
        request.GET.get("section") or
        request.GET.get("active_section")
    )

    def redirect_admin(section=None):
        section = normalize_section(section or active_section)
        return redirect(f"{reverse('admin_dashboard')}?section={section}")

    profile = get_object_or_404(UserProfile, user=request.user)

    # Only admin users can access admin dashboard
    if profile.role != "admin":
        return redirect("provider_workspace")

    if request.method == "POST":
        action = request.POST.get("action")

        # Add provider account
        if action == "add_provider":
            active_section = "providers"
            username = request.POST.get("username")
            email = request.POST.get("email")
            password = request.POST.get("password")

            if User.objects.filter(username=username).exists():
                error = "A user with this username already exists."
            else:
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                )

                UserProfile.objects.create(
                    user=user,
                    role="provider",
                    is_active_provider=True,
                )

                return redirect_admin("providers")

        # Activate / deactivate provider account
        elif action == "toggle_provider":
            active_section = "providers"
            provider_profile_id = request.POST.get("provider_profile_id")

            provider_profile = get_object_or_404(
                UserProfile,
                id=provider_profile_id,
                role="provider",
            )

            provider_profile.is_active_provider = not provider_profile.is_active_provider
            provider_profile.save(update_fields=["is_active_provider"])

            return redirect_admin("providers")
        
        # View encounter in read-only admin mode
        elif action == "view_encounter":
            encounter_id = request.POST.get("encounter_id")

            encounter = get_object_or_404(
                Encounter.objects.select_related(
                    "provider",
                    "patient",
                ),
                id=encounter_id,
            )

            note_versions = encounter.versions.all().order_by("-saved_at")
            latest_note_version = note_versions.first()

            return render(request, "view_encounter.html", {
                "encounter": encounter,
                "provider": encounter.provider,
                "patient": encounter.patient,
                "note_versions": note_versions,
                "latest_note_version": latest_note_version,
                "active_section": "encounters",
            })

        # Create note template
        elif action == "create_template":
            active_section = "templates"
            template_name = request.POST.get("template_name")
            encounter_type = request.POST.get("encounter_type", "")
            prompt_text = request.POST.get("prompt_text")

            NoteTemplate.objects.create(
                name=template_name,
                encounter_type=encounter_type,
                prompt_text=prompt_text,
                is_active=True,
            )

            return redirect_admin("templates")
        
        # Save / update note template
        elif action == "save_template":
            active_section = "templates"
            template_id = request.POST.get("template_id")

            template_name = request.POST.get("template_name")
            encounter_type = request.POST.get("encounter_type", "")
            prompt_text = request.POST.get("prompt_text")
            is_active = request.POST.get("is_active") == "on"

            template = get_object_or_404(
                NoteTemplate,
                id=template_id,
            )

            template.name = template_name
            template.encounter_type = encounter_type
            template.prompt_text = prompt_text
            template.is_active = is_active

            template.save(
                update_fields=[
                    "name",
                    "encounter_type",
                    "prompt_text",
                    "is_active",
                    "updated_at",
                ]
            )

            return redirect_admin("templates")

        # Deactivate note template instead of deleting it
        elif action == "toggle_template":
            active_section = "templates"
            template_id = request.POST.get("template_id")

            template = get_object_or_404(NoteTemplate, id=template_id)
            template.is_active = not template.is_active
            template.save(update_fields=["is_active", "updated_at"])

            return redirect_admin("templates")

        # Delete note template
        elif action == "delete_template":
            active_section = "templates"
            template_id = request.POST.get("template_id")

            template = get_object_or_404(NoteTemplate, id=template_id)
            template.delete()

            return redirect_admin("templates")

    # GET filters for encounters
    provider_profile_id = request.GET.get("provider")
    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")

    encounters = Encounter.objects.select_related(
        "provider",
        "patient",
    ).order_by("-updated_at")

    if provider_profile_id:
        provider_profile = UserProfile.objects.filter(
            id=provider_profile_id,
            role="provider",
        ).select_related("user").first()

        if provider_profile:
            encounters = encounters.filter(provider=provider_profile.user)

    if start_date:
        encounters = encounters.filter(updated_at__date__gte=start_date)

    if end_date:
        encounters = encounters.filter(updated_at__date__lte=end_date)

    providers = UserProfile.objects.filter(
        role="provider"
    ).select_related(
        "user"
    ).order_by(
        "user__username"
    )

    templates = NoteTemplate.objects.all().order_by("name")

    return render(request, "admin_dashboard.html", {
        "error": error,
        "encounters": encounters,
        "providers": providers,
        "templates": templates,
        "active_section": active_section,
        "selected_provider": provider_profile_id,
        "start_date": start_date,
        "end_date": end_date,
    })





def logout_view(request):
    logout(request)
    return redirect("login")