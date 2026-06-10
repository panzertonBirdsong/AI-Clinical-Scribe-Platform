from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import (
    UserProfile,
    Patient,
    NoteTemplate,
    Encounter,
    NoteVersion,
    ICD10Code,
    AuditLog,
)

admin.site.register(UserProfile)
admin.site.register(Patient)
admin.site.register(NoteTemplate)
admin.site.register(Encounter)
admin.site.register(NoteVersion)
admin.site.register(ICD10Code)
admin.site.register(AuditLog)