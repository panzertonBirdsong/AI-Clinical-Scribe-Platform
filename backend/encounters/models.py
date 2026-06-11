from django.db import models
from django.db.models import Q
from django.contrib.auth.models import User


class UserProfile(models.Model):
    ROLE_CHOICES = [
        ("provider", "Provider"),
        ("admin", "Admin"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)

    is_active_provider = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.user.username} - {self.role}"


class Patient(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField()

    class Meta:
        unique_together = ("first_name", "last_name", "date_of_birth")

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.date_of_birth})"


class NoteTemplate(models.Model):
    name = models.CharField(max_length=100)
    encounter_type = models.CharField(max_length=100, blank=True)
    prompt_text = models.TextField()
    is_active = models.BooleanField(default=True)

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Encounter(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("finalized", "Finalized"),
    ]

    provider = models.ForeignKey(User, on_delete=models.CASCADE)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)

    raw_input = models.TextField(blank=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="draft",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.patient} - {self.provider.username} - {self.status}"


class NoteVersion(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("finalized", "Finalized"),
    ]

    encounter = models.ForeignKey(
        Encounter,
        on_delete=models.CASCADE,
        related_name="versions",
    )

    version_number = models.PositiveIntegerField()
    note_text = models.TextField()

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="draft",
    )

    saved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
    )

    saved_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-version_number"]

        constraints = [
            models.UniqueConstraint(
                fields=["encounter", "version_number"],
                name="unique_note_version_per_encounter",
            ),
            models.UniqueConstraint(
                fields=["encounter"],
                condition=Q(status="draft"),
                name="unique_draft_note_per_encounter",
            ),
        ]

    def __str__(self):
        return (
            f"Encounter {self.encounter.id} - "
            f"Version {self.version_number} - "
            f"{self.status}"
        )

class ICD10Code(models.Model):
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField()

    keywords = models.TextField(blank=True)

    def __str__(self):
        return f"{self.code} - {self.description}"


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ("login", "Login"),
        ("logout", "Logout"),
        ("create_encounter", "Create Encounter"),
        ("generate_note", "Generate Note"),
        ("save_note", "Save Note"),
        ("update_template", "Update Template"),
        ("deactivate_provider", "Deactivate Provider"),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    details = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.action} by {self.user} at {self.created_at}"