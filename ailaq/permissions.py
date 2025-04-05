from rest_framework.permissions import BasePermission


class IsVerifiedPsychologist(BasePermission):
    """
    Custom permission to only allow access to users who are verified psychologists.
    """

    def has_permission(self, request, view):
        # Check if the user is authenticated
        if not request.user or not request.user.is_authenticated:
            return False

        # Check if the user is a psychologist
        if not request.user.is_psychologist:
            return False

        # Retrieve the psychologist profile and check if it exists and is verified
        profile = getattr(request.user, 'psychologist_profile', None)
        if profile is None:
            return False

        return profile.is_verified