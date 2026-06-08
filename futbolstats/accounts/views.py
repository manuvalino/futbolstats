"""
accounts/views.py
Registro, login y logout de usuarios
"""

from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from .forms import RegistroForm


def registro(request):
    """Vista de registro de nuevo usuario."""
    if request.method == "POST":
        form = RegistroForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"¡Bienvenido, {user.username}!")
            return redirect("/")
        else:
            messages.error(request, "Por favor corrige los errores del formulario.")
    else:
        form = RegistroForm()
    return render(request, "accounts/registro.html", {"form": form})


def login_view(request):
    """Vista de inicio de sesión."""
    if request.user.is_authenticated:
        return redirect("/")
    if request.method == "POST":
        form = AuthenticationForm(data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"¡Bienvenido de nuevo, {user.username}!")
            next_url = request.GET.get("next") or "/"
            if not url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                next_url = "/"
            return redirect(next_url)
        else:
            # Gestión de error de login 
            messages.error(request, "Usuario o contraseña incorrectos.")
    else:
        form = AuthenticationForm()
    return render(request, "accounts/login.html", {"form": form})


@require_POST
def logout_view(request):
    """Cierre de sesión."""
    logout(request)
    messages.info(request, "Has cerrado sesión correctamente.")
    return redirect("/accounts/login/")
