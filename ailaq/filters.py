from django_filters import rest_framework as filters
from ailaq.models import PsychologistProfile

class PsychologistProfileFilter(filters.FilterSet):
    gender = filters.CharFilter(field_name="application__gender", lookup_expr="iexact")
    min_price = filters.NumberFilter(field_name="application__session_price", lookup_expr="gte")
    max_price = filters.NumberFilter(field_name="application__session_price", lookup_expr="lte")
    city = filters.CharFilter(field_name="application__city", lookup_expr="icontains")
    is_verified = filters.BooleanFilter(field_name="is_verified")
    communication_language = filters.CharFilter(
        field_name="application__communication_language", lookup_expr="iexact"
    )

    class Meta:
        model = PsychologistProfile
        fields = [
            "gender",
            "min_price",
            "max_price",
            "city",
            "is_verified",
            "communication_language",
        ]