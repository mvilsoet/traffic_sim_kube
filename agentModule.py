import random
import json
from sqsUtility import send_sqs_message, process_sqs_messages

# Load configuration
with open('config.json', 'r') as config_file:
    CONFIG = json.load(config_file)

# Parameters from config
ROAD_LENGTH = CONFIG['roads']['length']
ACCELERATION = CONFIG['vehicles']['acceleration']
INITIAL_VEHICLES = CONFIG['vehicles']['initial_count']
INITIAL_ROAD = CONFIG['roads']['initial_road']
SQS_QUEUE_VEHICLE_UPDATES = CONFIG['sqs']['queue_vehicle_updates']
SQS_QUEUE_TRAFFIC_UPDATES = CONFIG['sqs']['queue_traffic_updates']

class Vehicle:
    def __init__(self, vehicle_id, start_road):
        self.id = vehicle_id
        self.current_road = start_road
        self.position = 0
        self.speed = 0
        self.x = random.randint(0, CONFIG['visualization']['grid_width'] - 1)
        self.y = random.randint(0, CONFIG['visualization']['grid_height'] - 1)

    def update(self, road_info):
        if road_info:
            self.speed = min(self.speed + ACCELERATION, road_info['speed_limit'])
            self.position += self.speed

            if self.position >= ROAD_LENGTH:
                self.position = 0
                self.current_road = random.choice(list(road_info['available_roads']))
                # Update x and y when changing roads
                self.x = random.randint(0, CONFIG['visualization']['grid_width'] - 1)
                self.y = random.randint(0, CONFIG['visualization']['grid_height'] - 1)

        return {
            'vehicle_id': self.id,
            'current_road': self.current_road,
            'position': self.position,
            'speed': self.speed,
            'x': self.x,
            'y': self.y
        }

class AgentModule:
    def __init__(self):
        self.vehicles = []
        self.next_vehicle_id = 0

    def create_vehicle(self, start_road):
        vehicle = Vehicle(self.next_vehicle_id, start_road)
        self.vehicles.append(vehicle)
        self.next_vehicle_id += 1
        return vehicle

    def update_all(self):
        for vehicle in self.vehicles:
            send_sqs_message(SQS_QUEUE_VEHICLE_UPDATES, {
                'type': 'road_info_request',
                'road_id': vehicle.current_road
            })

        def process_message(message):
            if message['type'] == 'road_info_response':
                for vehicle in self.vehicles:
                    if vehicle.current_road == message['road_id']:
                        update_data = vehicle.update(message['road_info'])
                        send_sqs_message(SQS_QUEUE_VEHICLE_UPDATES, update_data)
            elif message['type'] == 'create_vehicle':
                if 'start_road' in message:
                    new_vehicle = self.create_vehicle(message['start_road'])
                    update_data = new_vehicle.update(None)  # Initial update without road info
                    send_sqs_message(SQS_QUEUE_VEHICLE_UPDATES, update_data)
                else:
                    print("Error: create_vehicle message missing start_road")

        process_sqs_messages(SQS_QUEUE_VEHICLE_UPDATES, process_message)
        process_sqs_messages(SQS_QUEUE_TRAFFIC_UPDATES, process_message)

if __name__ == "__main__":
    agent_module = AgentModule()
    for _ in range(INITIAL_VEHICLES):
        agent_module.create_vehicle(INITIAL_ROAD)

    while True:
        agent_module.update_all()
