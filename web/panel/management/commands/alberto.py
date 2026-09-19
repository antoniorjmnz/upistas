"""`manage.py alberto`: el usuario de la demo (alberto / alberto), si no existe ya."""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Crea el usuario alberto (contraseña alberto) para entrar en la web, si no existe"

    def handle(self, *args, **options):
        usuario, creado = get_user_model().objects.get_or_create(
            username="alberto", defaults={"is_staff": True, "is_superuser": True, "first_name": "Alberto"},
        )
        if creado:
            usuario.set_password("alberto")
            usuario.save()
        self.stdout.write("Usuario alberto creado" if creado else "El usuario alberto ya existía")
