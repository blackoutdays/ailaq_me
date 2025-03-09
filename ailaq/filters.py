from django_filters import rest_framework as filters
from ailaq.models import PsychologistProfile

class PsychologistProfileFilter(filters.FilterSet):
    gender = filters.CharFilter(field_name="application__gender", lookup_expr="iexact")
    min_price = filters.NumberFilter(method="filter_min_price")
    max_price = filters.NumberFilter(method="filter_max_price")
    city = filters.CharFilter(field_name="application__city", lookup_expr="icontains")
    is_verified = filters.BooleanFilter(field_name="is_verified")
    communication_language = filters.CharFilter(field_name="application__communication_language", lookup_expr="iexact")

    class Meta:
        model = PsychologistProfile
        fields = [
            "gender",
            "city",
            "is_verified",
            "communication_language",
        ]

    def filter_min_price(self, queryset, name, value):
        return queryset.filter(application__service_sessions__contains=[{"price": value}])

    def filter_max_price(self, queryset, name, value):
        return queryset.filter(application__service_sessions__contains=[{"price": value}])