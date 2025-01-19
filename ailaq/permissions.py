# permissions.py
from rest_framework.permissions import BasePermission

class IsVerifiedPsychologist(BasePermission):
    """
    Доступ только для авторизованных пользователей (is_authenticated),
    у которых is_psychologist=True
    и PsychologistProfile.is_verified=True.
    """

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if not user.is_psychologist:
            return False

        profile = getattr(user, 'psychologist_profile', None)
        return bool(profile and profile.is_verified)