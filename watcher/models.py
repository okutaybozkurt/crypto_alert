# watcher/models.py
from django.db import models

class Token(models.Model):
    contract_address = models.CharField(max_length=80, unique=True)  # EVM(42) + Solana(44) rahat sığar
    def __str__(self):
        return self.contract_address

class User(models.Model):
    telegram_id = models.CharField(max_length=50, unique=True)
    username = models.CharField(max_length=150, null=True, blank=True)

    def __str__(self):
        return self.username or self.telegram_id

class UserToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    token = models.ForeignKey(Token, on_delete=models.CASCADE)
    threshold_low = models.FloatField(default=500)
    threshold_mid = models.FloatField(default=1000)
    threshold_high = models.FloatField(default=1500)

    # --- yeni alanlar ---
    last_alert_level = models.CharField(
        max_length=10,
        choices=[("none", "none"), ("low", "low"), ("mid", "mid"), ("high", "high")],
        default="none",
    )
    last_seen_mcap = models.FloatField(null=True, blank=True)  # son görülen market cap
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("user", "token"),)

    def __str__(self):
        return f"{self.user} - {self.token}"
