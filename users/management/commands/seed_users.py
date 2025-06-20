from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from users.models import UserProfile

class Command(BaseCommand):
    help = "Seed initial users without passwords"

    def handle(self, *args, **kwargs):
        names = [
            "BÜLENT AYDIN", "ORHAN ÇELİK", "MEHMET YEŞİL", "SEZER ÇAĞLAR", "ŞENDOĞAN ŞİRİN",
            "MEHMET IŞIK", "FERDİ IŞIK", "CEYHUN AKIN", "ALPER YILMAZ", "ABDURRAHİM FETVACI",
            "BEKİR AYDIN", "HÜSEYİN HIZARCIOĞLU", "NUSRET ÇAYIR", "LEVENT KIZILKAYA", "ALGIN ÇIBIK",
            "ADEM GÜREL", "MUSTAFA SEMİZ", "YÜKSEL ÖZTÜRK", "YÜKSEL ÇEBİ", "SEYİTHAN ACAR"
        ]

        team = "Machining"

        for full_name in names:
            username = (
                full_name.lower()
                .replace("ç", "c").replace("ş", "s").replace("ı", "i")
                .replace("ğ", "g").replace("ü", "u").replace("ö", "o")
                .replace(" ", "").replace(".", "").replace("-", "")
            )

            user, created = User.objects.get_or_create(username=username)

            if created:
                user.set_unusable_password()
                user.save()
                self.stdout.write(self.style.SUCCESS(f"✅ Created: {username}"))
            else:
                self.stdout.write(self.style.WARNING(f"⏭ Already exists: {username}"))

            # Assign team in profile
            profile = user.profile
            profile.team = team
            profile.save()
