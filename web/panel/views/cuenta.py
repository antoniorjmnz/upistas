"""Entrar y salir. Todo lo demás exige sesión (LoginRequiredMiddleware en web/settings.py)."""
from __future__ import annotations

from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import LoginView, LogoutView

entrar = login_not_required(LoginView.as_view(template_name="panel/entrar.html", redirect_authenticated_user=True))
salir = LogoutView.as_view()
