from django.contrib.auth import get_user_model
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from ailaq.models import CustomUser, PsychologistApplication, PsychologistProfile, ClientProfile, PsychologistLevel

class CustomUserCreationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = CustomUser
        fields = ['email', 'password', 'is_psychologist', 'role']

    @extend_schema_field(serializers.CharField())
    def get_role(self, obj):
        return obj.role

    def create(self, validated_data):
        from ailaq.models import CustomUser, PsychologistApplication

        user = CustomUser.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            is_psychologist=validated_data.get('is_psychologist', False),
        )

        if user.is_psychologist:
            PsychologistApplication.objects.create(user=user)

        return user

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        email = data.get("email")
        password = data.get("password")

        user = get_user_model().objects.filter(email=email).first()
        if not user or not user.check_password(password):
            raise serializers.ValidationError("Invalid credentials")

        return data

class PsychologistProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = PsychologistProfile
        fields = '__all__'

class PsychologistApplicationSerializer(serializers.ModelSerializer):
    level = serializers.StringRelatedField()

    class Meta:
        model = PsychologistApplication
        fields = '__all__'

class ClientProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientProfile
        fields = '__all__'

class PsychologistLevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = PsychologistLevel
        fields = '__all__'