from django.db import models
# Create your models here.

class CurrencyRateSnapshot(models.Model):
    provider = models.CharField(max_length=50, default="freecurrencyapi")
    date = models.DateField(unique=True, db_index=True)   # UTC day
    base = models.CharField(max_length=3, default="TRY")  # fixed base
    rates = models.JSONField()                            # {"EUR": 0.91, "TRY": 33.2, ...}
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.provider} {self.date} base={self.base}"