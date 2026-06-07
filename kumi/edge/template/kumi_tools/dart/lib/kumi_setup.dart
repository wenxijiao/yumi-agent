import 'package:kumi_sdk/kumi_sdk.dart';

void initKumi() {
  final agent = KumiAgent(
    AgentOptions(edgeName: 'My Dart App'),
  );
  agent.register(
    RegisterOptions(
      name: 'hello',
      description: 'Say hello to someone',
      parameters: [
        ToolParameter(
          name: 'name',
          typeName: 'string',
          description: 'Person to greet',
        ),
      ],
      handler: (args) {
        final n = args.string('name');
        if (n.isEmpty) return 'Hello, World!';
        return 'Hello, $n!';
      },
      // Read-only tools can opt in to proactive messaging:
      // allowProactive: true,
      // proactiveContext: true,
    ),
  );
  agent.runInBackground();
}
