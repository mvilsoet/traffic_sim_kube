import json
import time
import logging
import dash
from dash import html, dcc
from dash.dependencies import Input, Output, State
import plotly.graph_objs as go
from sqsUtility import process_sqs_messages, send_sqs_message
from threading import Thread
import queue
import random

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load configuration
with open('config.json', 'r') as config_file:
    CONFIG = json.load(config_file)

GRID_WIDTH = CONFIG['visualization']['grid_width']
GRID_HEIGHT = CONFIG['visualization']['grid_height']
SQS_QUEUE_VEHICLE_UPDATES = CONFIG['sqs']['queue_vehicle_updates']
SQS_QUEUE_TRAFFIC_UPDATES = CONFIG['sqs']['queue_traffic_updates']

class VisualizationModule:
    def __init__(self):
        self.vehicles = {}
        self.traffic_lights = {}
        self.road_blockages = {}
        self.roads = {}
        self.update_queue = queue.Queue()

    def process_messages(self):
        def process_vehicle_message(message):
            if 'vehicle_id' in message:
                self.update_queue.put(('vehicle', message))

        def process_traffic_message(message):
            if message['type'] == 'traffic_light_update':
                self.update_queue.put(('traffic_light', message))
            elif message['type'] == 'road_blockage_update':
                self.update_queue.put(('road_blockage', message))
            elif message['type'] == 'road_network_update':
                self.update_queue.put(('road_network', message))
                logging.info(f"Received road network update with {len(message['roads'])} roads")

        while True:
            process_sqs_messages(SQS_QUEUE_VEHICLE_UPDATES, process_vehicle_message)
            process_sqs_messages(SQS_QUEUE_TRAFFIC_UPDATES, process_traffic_message)

    def create_random_roadblock(self):
        if not self.roads:
            logging.warning("No roads available for creating a roadblock.")
            return

        road_id = random.choice(list(self.roads.keys()))
        message = {
            'type': 'create_road_blockage',
            'road_id': road_id,
            'duration': random.randint(10, 60)  # Random duration between 10 and 60 seconds
        }
        send_sqs_message(SQS_QUEUE_TRAFFIC_UPDATES, message)
        logging.info(f"Created random roadblock on road {road_id}")

    def create_random_vehicle(self):
        if not self.roads:
            logging.warning("No roads available for creating a vehicle.")
            return

        road_id = random.choice(list(self.roads.keys()))
        message = {
            'type': 'create_vehicle',
            'start_road': road_id
        }
        send_sqs_message(SQS_QUEUE_VEHICLE_UPDATES, message)
        logging.info(f"Created random vehicle on road {road_id}")

    def run(self):
        app = dash.Dash(__name__)

        app.layout = html.Div([
            html.Div([
                html.Button('Create Random Roadblock', id='create-roadblock-button', n_clicks=0),
                html.Button('Create Random Vehicle', id='create-vehicle-button', n_clicks=0),
            ], style={'padding': '10px'}),
            dcc.Graph(id='live-graph', animate=True),
            dcc.Interval(
                id='graph-update',
                interval=1000,  # in milliseconds
                n_intervals=0
            )
        ])

        @app.callback(
            Output('live-graph', 'figure'),
            Input('graph-update', 'n_intervals'),
            Input('create-roadblock-button', 'n_clicks'),
            Input('create-vehicle-button', 'n_clicks'),
            State('live-graph', 'figure')
        )
        def update_graph_scatter(n, roadblock_clicks, vehicle_clicks, current_figure):
            ctx = dash.callback_context
            if not ctx.triggered:
                button_id = 'No clicks yet'
            else:
                button_id = ctx.triggered[0]['prop_id'].split('.')[0]

            if button_id == 'create-roadblock-button':
                self.create_random_roadblock()
            elif button_id == 'create-vehicle-button':
                self.create_random_vehicle()

            while not self.update_queue.empty():
                update_type, data = self.update_queue.get()
                if update_type == 'vehicle':
                    self.vehicles[data['vehicle_id']] = (data['x'], data['y'])
                elif update_type == 'traffic_light':
                    intersection_id = data['intersection_id']
                    x, y = divmod(hash(intersection_id), GRID_WIDTH)
                    self.traffic_lights[intersection_id] = (x % GRID_WIDTH, y % GRID_HEIGHT, data['state'])
                elif update_type == 'road_blockage':
                    road_id = data['road_id']
                    if data['is_blocked']:
                        x, y = divmod(hash(road_id), GRID_WIDTH)
                        self.road_blockages[road_id] = (x % GRID_WIDTH, y % GRID_HEIGHT)
                    elif road_id in self.road_blockages:
                        del self.road_blockages[road_id]
                elif update_type == 'road_network':
                    self.roads = data['roads']
                    logging.info(f"Updated road network with {len(self.roads)} roads")

            road_traces = []
            for road_id, road_info in self.roads.items():
                start, end = road_info['start'], road_info['end']
                road_traces.append(go.Scatter(
                    x=[start[0], end[0]],
                    y=[start[1], end[1]],
                    mode='lines',
                    line=dict(color='gray', width=1, dash='dot'),
                    hoverinfo='none',
                    showlegend=False
                ))

            vehicle_trace = go.Scatter(
                x=[x for x, y in self.vehicles.values()],
                y=[y for x, y in self.vehicles.values()],
                mode='markers',
                name='Vehicles',
                marker=dict(color='blue', size=10, symbol='circle')
            )

            traffic_light_trace = go.Scatter(
                x=[x for x, y, state in self.traffic_lights.values()],
                y=[y for x, y, state in self.traffic_lights.values()],
                mode='markers',
                name='Traffic Lights',
                marker=dict(
                    color=['green' if state == 'Green' else 'red' for _, _, state in self.traffic_lights.values()],
                    size=15,
                    symbol='circle'
                )
            )

            road_blockage_trace = go.Scatter(
                x=[x for x, y in self.road_blockages.values()],
                y=[y for x, y in self.road_blockages.values()],
                mode='markers',
                name='Road Blockages',
                marker=dict(color='red', size=12, symbol='x')
            )

            # Add border lines
            border_trace = go.Scatter(
                x=[0, GRID_WIDTH, GRID_WIDTH, 0, 0],
                y=[0, 0, GRID_HEIGHT, GRID_HEIGHT, 0],
                mode='lines',
                name='Grid Border',
                line=dict(color='black', width=2),
                hoverinfo='none'
            )

            return {
                'data': road_traces + [vehicle_trace, traffic_light_trace, road_blockage_trace, border_trace],
                'layout': go.Layout(
                    xaxis=dict(range=[-1, GRID_WIDTH + 1], showgrid=False, zeroline=False),
                    yaxis=dict(range=[-1, GRID_HEIGHT + 1], showgrid=False, zeroline=False),
                    title='Traffic Simulation',
                    showlegend=True,
                    legend=dict(x=0, y=1),
                    margin=dict(l=40, r=40, t=40, b=40)
                )
            }

        # Start the message processing in a separate thread
        Thread(target=self.process_messages, daemon=True).start()

        # Run the Dash app
        app.run_server(debug=True, host='0.0.0.0', port=8050)

if __name__ == "__main__":
    viz = VisualizationModule()
    viz.run()
