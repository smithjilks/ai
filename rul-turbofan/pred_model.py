import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import joblib
import seaborn as sns
import matplotlib.pyplot as plt
from torch.utils.data import DataLoader, Dataset

# Load datasets
test_df = pd.read_csv('test_FD003.txt', sep=r'\s+', header=None)
rul_df = pd.read_csv('RUL_FD003.txt', sep=r'\s+', header=None)

column_names = ['id', 'cycle'] + ['setting1', 'setting2', 'setting3'] + ['s' + str(i) for i in range(1, 22)]
test_df.columns = column_names
rul_df.columns = ['RUL']

# Load scaler
scaler = joblib.load('scaler.pkl')
cols_normalize = test_df.columns.difference(['id', 'cycle'])

# Normalize test data
test_df[cols_normalize] = scaler.transform(test_df[cols_normalize])

# Add actual RUL to test dataset
max_cycles = test_df.groupby('id')['cycle'].max()
actual_rul = pd.concat([max_cycles, rul_df], axis=1).reset_index()
actual_rul.columns = ['id', 'max_cycle', 'RUL']
test_df = pd.merge(test_df, actual_rul, on='id', how='left')
test_df['RUL'] = test_df['max_cycle'] + test_df['RUL'] - test_df['cycle']
test_df.drop(columns=['max_cycle'], inplace=True)

# Dataset class
class TurbofanTestDataset(Dataset):
    def __init__(self, data, sequence_length):
        self.data = data
        self.sequence_length = sequence_length
        self.valid_indices = self._get_valid_indices()

    def _get_valid_indices(self):
        valid_indices = []
        for unit_id in self.data['id'].unique():
            unit_data = self.data[self.data['id'] == unit_id]
            if len(unit_data) >= self.sequence_length:
                valid_indices.extend(range(unit_data.index[0], unit_data.index[-1] - self.sequence_length + 2))
        return valid_indices

    def __len__(self):
        return len(self.valid_indices)

    def __getitem__(self, idx):
        actual_idx = self.valid_indices[idx]
        unit_id = self.data.iloc[actual_idx]['id']
        unit_data = self.data[self.data['id'] == unit_id]
        start = actual_idx - unit_data.index[0]
        sequence = unit_data.iloc[start:start + self.sequence_length].drop(columns=['id', 'cycle', 'RUL']).values
        target = unit_data.iloc[start + self.sequence_length - 1]['RUL']
        return torch.tensor(sequence, dtype=torch.float32), torch.tensor(target, dtype=torch.float32)

# Load the saved model
class LSTMModel(nn.Module):
    def __init__(self, input_dim, hidden_dim, num_layers, output_dim):
        super(LSTMModel, self).__init__()
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers
        self.lstm = nn.LSTM(input_dim, hidden_dim, num_layers, batch_first=True, dropout=0.5)
        self.fc = nn.Linear(hidden_dim, output_dim)

    def forward(self, x):
        h0 = torch.zeros(self.num_layers, x.size(0), self.hidden_dim).to(x.device)
        c0 = torch.zeros(self.num_layers, x.size(0), self.hidden_dim).to(x.device)
        out, _ = self.lstm(x, (h0, c0))
        out = self.fc(out[:, -1, :])
        return out

# Set device and load the model
device = 'cuda' if torch.cuda.is_available() else 'cpu'
input_dim = len(cols_normalize)
hidden_dim = 128
num_layers = 3
output_dim = 1
sequence_length = 50

model = LSTMModel(input_dim, hidden_dim, num_layers, output_dim)
model.load_state_dict(torch.load('model.pth', map_location=device))
model = model.to(device)
model.eval()

# Prepare test dataset and dataloader
test_dataset = TurbofanTestDataset(test_df, sequence_length)
test_loader = DataLoader(test_dataset, batch_size=1, shuffle=False)

# Perform prediction
results = []
with torch.no_grad():
    for idx, (sequences, actual_ruls) in enumerate(test_loader):
        sequences = sequences.to(device)
        predicted_ruls = model(sequences).cpu().numpy()
        unit_id = test_df.iloc[idx]['id']
        cycle = test_df.iloc[idx]['cycle']
        results.append((unit_id, cycle, actual_ruls.item(), predicted_ruls.item()))

result_df = pd.DataFrame(results, columns=['id', 'cycle', 'RUL', 'Predicted_RUL'])

# Visualize actual vs predicted RUL
def visualize_actual_vs_predicted(df):
    plt.figure(figsize=(20, 10))
    sns.set_style('whitegrid')
    
    sns.lineplot(x='cycle', y='RUL', data=df, label='Actual RUL', color='blue')
    sns.lineplot(x='cycle', y='Predicted_RUL', data=df, label='Predicted RUL', color='red')

    plt.xlabel('Cycle')
    plt.ylabel('RUL')
    plt.title('Actual vs Predicted Remaining Useful Life (RUL)')
    plt.legend()
    plt.tight_layout()
    plt.show()

visualize_actual_vs_predicted(result_df)
