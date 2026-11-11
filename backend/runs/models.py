import uuid

from django.db import models


class Run(models.Model):
    STATUS_CHOICES = [("done", "Done"), ("failed", "Failed")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    input_hash = models.CharField(max_length=64, unique=True, db_index=True)
    status = models.CharField(max_length=8, choices=STATUS_CHOICES, default="done")
    created_at = models.DateTimeField(auto_now_add=True)
    duration_ms = models.PositiveIntegerField(default=0)
    scenario_json = models.JSONField()
    result_summary = models.JSONField()
    result_frames = models.BinaryField()

    class Meta:
        ordering = ["-created_at"]
