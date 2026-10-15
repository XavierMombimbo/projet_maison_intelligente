part of '../app.dart';

class HouseEditScreen extends StatelessWidget {
  const HouseEditScreen({super.key, required this.controller, required this.house});
  final AppController controller;
  final MobileHouse house;

  @override
  Widget build(BuildContext context) => _HouseForm(controller: controller, house: house);
}
