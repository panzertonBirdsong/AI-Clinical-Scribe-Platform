from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout

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
                    "template",
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
            "template",
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
            "template",
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
    encounter = get_object_or_404(
        Encounter.objects.select_related(
            "provider",
            "patient",
            "template",
        ),
        id=encounter_id,
        provider=request.user,
    )

    if request.method == "POST":
        raw_text = request.POST.get("raw_text", "")
        template_id = request.POST.get("template_id")

        # Save latest raw input first
        encounter.raw_input = raw_text

        # Generate SOAP note from raw input
        generated_note = call_llm(encounter_id, template_id)

        # Save generated note into encounter
        encounter.current_note = generated_note
        encounter.save()

        # Create new note version
        latest_version = encounter.versions.order_by("-version_number").first()

        if latest_version:
            next_version_number = latest_version.version_number + 1
        else:
            next_version_number = 1

        NoteVersion.objects.create(
            encounter=encounter,
            version_number=next_version_number,
            note_text=generated_note,
            saved_by=request.user,
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



@login_required
def save_note_version(request, encounter_id):
    encounter = get_object_or_404(
        Encounter.objects.select_related(
            "provider",
            "patient",
            "template",
        ),
        id=encounter_id,
        provider=request.user,
    )

    if request.method == "POST":
        note_text = request.POST.get("note_text", "")

        # Update the encounter's current note
        encounter.current_note = note_text
        encounter.save()

        # Create a new saved version
        latest_version = encounter.versions.order_by("-version_number").first()

        if latest_version:
            next_version_number = latest_version.version_number + 1
        else:
            next_version_number = 1

        NoteVersion.objects.create(
            encounter=encounter,
            version_number=next_version_number,
            note_text=note_text,
            saved_by=request.user,
        )

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
def admin_dashboard(request):
    return HttpResponse("Admin dashboard page")





def logout_view(request):
    return HttpResponse("logout")