"""
accounts/forms.py
Formularios de registro y login.
"""

from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import PerfilUsuario


class RegistroForm(UserCreationForm):
    email = forms.EmailField(required=True, label="Correo electrónico")
    equipo_favorito = forms.CharField(
        max_length=100,
        required=False,
        initial="RC Deportivo de La Coruña",
        label="Equipo favorito",
    )

    class Meta:
        model = User
        fields = ["username", "email", "password1", "password2"]

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            PerfilUsuario.objects.create(
                usuario=user,
                equipo_favorito=self.cleaned_data.get("equipo_favorito", ""),
            )
        return user
