import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
django.setup()

from django.contrib.auth.models import User
from encounters.models import UserProfile, NoteTemplate, ICD10Code


demo_users = [
    ("admin1", "admin123", "admin"),
    ("provider1", "provider123", "provider"),
    ("provider2", "provider123", "provider"),
    ("provider3", "provider123", "provider"),
]

for username, password, role in demo_users:
    user, _ = User.objects.get_or_create(username=username)
    user.set_password(password)
    user.is_active = True

    user.is_staff = False
    user.is_superuser = False

    user.save()

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.role = role
    profile.is_active_provider = True
    profile.save()


templates = [
    (
        "General SOAP Note",
        "General",
        "Generate a professional SOAP note with Subjective, Objective, Assessment with ICD-10 codes, and Plan.",
    ),
    (
        "Urgent Care Visit",
        "Urgent Care",
        "Generate a concise urgent-care SOAP note. Emphasize chief complaint, acute findings, diagnosis, treatment, and follow-up precautions.",
    ),
    (
        "Orthopedic Follow-up",
        "Orthopedic",
        "Generate an orthopedic follow-up SOAP note. Emphasize pain level, mobility, exam findings, imaging, assessment, and rehab plan.",
    ),
]

for name, encounter_type, prompt_text in templates:
    NoteTemplate.objects.get_or_create(
        name=name,
        defaults={
            "encounter_type": encounter_type,
            "prompt_text": prompt_text,
        },
    )


sample_codes = [
    ("R05.9", "Cough, unspecified", "cough respiratory"),
    ("R50.9", "Fever, unspecified", "fever chills infection"),
    ("J06.9", "Acute upper respiratory infection, unspecified", "cold uri congestion sore throat"),
    ("M54.50", "Low back pain, unspecified", "back pain lumbar"),
    ("E11.9", "Type 2 diabetes mellitus without complications", "diabetes glucose a1c"),
    ("I10", "Essential hypertension", "high blood pressure hypertension"),
    ("R07.9", "Chest pain, unspecified", "chest pain pressure"),
    ("R51.9", "Headache, unspecified", "headache migraine"),
]

for code, description, keywords in sample_codes:
    ICD10Code.objects.get_or_create(
        code=code,
        defaults={
            "description": description,
            "keywords": keywords,
        },
    )

print("Demo users, templates, and ICD-10 codes created.")