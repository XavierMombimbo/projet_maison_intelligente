from rest_framework import serializers


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=254, trim_whitespace=True)
    password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)
    device_id = serializers.RegexField(r"^[A-Za-z0-9._:-]{8,255}$")
    device_name = serializers.CharField(max_length=120, trim_whitespace=True)


class MFAVerifySerializer(serializers.Serializer):
    challenge = serializers.CharField(max_length=255, trim_whitespace=True, write_only=True)
    code = serializers.CharField(max_length=32, trim_whitespace=True, write_only=True)


class RefreshSerializer(serializers.Serializer):
    refresh_token = serializers.CharField(max_length=255, trim_whitespace=True, write_only=True)
