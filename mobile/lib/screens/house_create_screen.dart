part of '../app.dart';

class HouseCreateScreen extends StatelessWidget {
  const HouseCreateScreen({super.key, required this.controller});
  final AppController controller;

  @override
  Widget build(BuildContext context) => _HouseForm(controller: controller);
}
