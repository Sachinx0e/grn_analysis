import pandas
import networkx as nx
import random
import numpy as np

def load_original_expression():
    dataframe = pandas.read_csv('data/original/ecoli_10_4/Ecoli_subnet_10_4-1_dream4_timeseries.tsv', sep = '\t', header=0)
    dataframe = dataframe.drop('Time',axis=1)
    return dataframe

def extract_training_data(original_expression, percent):
    normalized_percent = percent * 0.01
    data_size = original_expression.shape[0] * normalized_percent
    dataframe = original_expression[:int(data_size)]
    dataframe = dataframe.T
    return dataframe


def extract_testing_data(original_expression, percent):
    normalized_percent = percent * 0.01
    data_size = original_expression.shape[0] * normalized_percent
    dataframe = original_expression.tail(int(data_size))
    dataframe = dataframe.T
    return dataframe


def load_gene_list(expression_data):
    return list(expression_data.columns.values)[:]


def train_grn(grn, training_data):
    weight_matrix = nx.to_numpy_matrix(grn.graph)
    print(weight_matrix)
    bias_matrix = grn.bias[:]
    gene_list = grn.genes

    training_data_count = training_data.columns.values.size

    # skip the first column, as we plan to use it later to feed into the first layer
    timestep_index = 1

    # loop over the training data
    while timestep_index < training_data_count:
        training_column = training_data.iloc[:,timestep_index].values
        prev_training_column = training_data.iloc[:,timestep_index-1].values

        training_column_size = training_column.size

        target_gene_index = 0

        print("TimeStep ", timestep_index)

        # loop over the genes
        while target_gene_index < training_column_size:

            # get the target gene
            target_gene = gene_list[target_gene_index]

            # get the target genes expression at this time point
            target_gene_expression = training_column[target_gene_index]
            target_gene_prev_expression = prev_training_column[target_gene_index]

            # get the bias for this gene
            bias = bias_matrix[target_gene_index]

            # get the regulator genes
            regulator_genes = grn.get_regulators(target_gene)

            # get the regulator gene count
            regulator_gene_count = len(regulator_genes)

            # array to hold the expression of regulators in previous time step
            regulators_prev_expression_matrix = np.zeros((regulator_gene_count,1))

            # array to hold the optimization matrix
            optimization_matrix = np.zeros((regulator_gene_count + 3,1))

            # add bias at first position
            optimization_matrix[0] = bias

            # add peak expression
            optimization_matrix[1] = grn.peak_expression_level[target_gene_index]

            # add degradation constant
            optimization_matrix[2] = grn.degradation_constant[target_gene_index]

            # loop over the target genes
            regulator_gene_index = 0
            while regulator_gene_index < regulator_gene_count:

                # get the regulator gene
                regulator_gene = regulator_genes[regulator_gene_index]

                # get original index of this regulator gene
                regulator_gene_original_index = gene_list.index(regulator_gene)

                # get the weight from the weight matrix
                weight_target_regulator = weight_matrix[target_gene_index,regulator_gene_index]

                # add the value to optimization matrix
                optimization_matrix[regulator_gene_index+3] = weight_target_regulator

                # get the expression of this regulator at previous time point
                regulator_prev_expression = prev_training_column[regulator_gene_original_index]

                # add to the prev regulator expression matrix
                regulators_prev_expression_matrix[regulator_gene_index] = regulator_prev_expression

                # update the invariant
                regulator_gene_index = regulator_gene_index + 1

            # lower bound and upper bound matrices for bapso
            lower_bound = np.zeros((regulator_gene_count + 1,1))
            lower_bound.fill(-1)
            upper_bound = np.ones((regulator_gene_count + 1,1))

            # start the training
            optimized_matrix = run_bapso(optimization_matrix,
                                        upper_bound,
                                        lower_bound,
                                        target_gene_expression,
                                        target_gene_prev_expression,
                                        regulators_prev_expression_matrix
                                        )

            # loop over the optimized values and update the original weight matrix
            optimized_data_index = 0
            while optimized_data_index < len(optimized_matrix):
                if optimized_data_index == 0:
                    bias = optimized_matrix[optimized_data_index]
                    bias_matrix[target_gene_index] = bias

                elif optimized_data_index == 1:
                    peak_expression = optimization_matrix[optimized_data_index]
                    grn.peak_expression_level[target_gene_index] = peak_expression

                elif optimized_data_index == 2:
                    degradation_constant = optimization_matrix[optimized_data_index]
                    grn.degradation_constant[target_gene_index] = degradation_constant

                else:
                    weight_target_regulator = optimized_matrix[optimized_data_index]
                    regulator_gene = regulator_genes[optimized_data_index - 3]
                    regulator_gene_index = gene_list.index(regulator_gene)
                    weight_matrix[target_gene_index,regulator_gene_index] = weight_target_regulator

                # update the invariant
                optimized_data_index = optimized_data_index + 1

            # update the invariant
            target_gene_index = target_gene_index + 1

        # update the invariant
        timestep_index = timestep_index + 1

    # recreate the graph from tne updated weight matrix
    print(weight_matrix)

    graph = nx.from_numpy_matrix(weight_matrix)
    grn.graph = graph
    grn.bias = bias_matrix
    grn.relabel_nodes()
    return grn


def run_bapso(optimization_matrix,
              optimization_upper_bound_matrix,
              optimization_lower_bound_matrix,
              target_gene_current_expression,
              target_gene_prev_expression,
              regulators_prev_expression_matrix):

    maxiter = 20

    global_best = np.random.rand((len(optimization_matrix)))
    best_error = -1

    num_of_particles = 20
    swarm = []

    # populate the swarm
    for particle_index in range(0,num_of_particles):
        particle = Particle(optimization_matrix)
        swarm.append(particle)

    # begin the optimization
    iteration_index = 0
    while iteration_index < maxiter:

        # cycle through particles in swarm and evaluate fitness
        particle_num = 0
        while particle_num < num_of_particles:
            particle = swarm[particle_num]

            particle.evaluate_fitness(target_gene_current_expression,regulators_prev_expression_matrix)

            # if current particles error is less than current best error
            if particle.current_error < best_error or best_error == -1:
                # update the best position
                global_best = particle.position

                # update the best error
                best_error = particle.current_error

            # update the invariant
            particle_num = particle_num + 1


        # cycle through particles in swarm and update state
        particle_num = 0
        while particle_num < num_of_particles:
            particle = swarm[particle_num]
            particle.update_state(global_best)

            # update the invariant
            particle_num = particle_num + 1

        # update invariant
        iteration_index = iteration_index + 1


    return global_best


class Particle:
    def __init__(self,initial_position):
        self.position = initial_position[:]
        self.velocity = np.zeros(len(self.position))
        self.best_position = np.random.rand(len(self.position))
        self.position = self.best_position[:]
        self.best_error = -1
        self.current_error = 0
        self.inertia = 0.5

    def update_state(self,global_best):

        r1 = random.uniform(0,1)
        r2 = random.uniform(0,1)
        c1 = 2
        c2 = 2

        # update the velocity and position
        value = (self.best_position - self.position) + (r2*c2)
        self.velocity = (self.inertia * self.velocity) + (r1*c1) * (self.best_position - self.position) + (r2*c2) * (global_best - self.position)
        self.position = self.velocity + self.position


    def evaluate_fitness(self,target_gene_current_expression,regulators_prev_expression_matrix):

        predicted_expression = 0
        regulator_index = 0

        bias = self.position[0]
        peak_expression = self.position[1]
        degradation_constant = self.position[2]

        while regulator_index < len(regulators_prev_expression_matrix):
            weight = self.position[regulator_index + 1]
            regulator_expression = regulators_prev_expression_matrix[regulator_index]
            regulator_express_contrib = weight * regulator_expression + bias
            predicted_expression = predicted_expression + regulator_express_contrib

            # update invariant
            regulator_index = regulator_index + 1

        predicted_expression = peak_expression * sigmoid(predicted_expression) - degradation_constant

        self.current_error =  ((target_gene_current_expression - predicted_expression)**2).mean()

        if self.current_error < self.best_error or self.best_error == -1:
            self.best_position = self.position
            self.best_error = self.current_error


def predict_expression(trained_grn,previous_expression_values,timepoints_to_predict):

    # get the weights
    weight_matrix = nx.to_numpy_array(trained_grn.graph)

    # get the bias
    bias_matrix = trained_grn.bias

    # matrix to hold the predicted values
    gene_count = len(trained_grn.genes)
    gene_labels = pandas.Series(trained_grn.genes)
    predicted_expression_matrix = pandas.DataFrame(np.zeros((len(trained_grn.genes),timepoints_to_predict)),index=gene_labels)

    hidden_state_matrix = np.random.rand(gene_count,1)

    combined_weight_matrix = build_combined_weight_matrix(weight_matrix)

    # the expression for previous time point
    expr_for_prev_timepoint = None

    # start looping to predict the values
    for timepoint_index in range(0,timepoints_to_predict):

        # matrix to hold expression for current time point
        expr_for_curr_timepoint = np.empty((gene_count,1))


        # if first time point then we use previous expression values
        if timepoint_index == 0:
            # if first then use previous expression values
            expr_for_prev_timepoint = previous_expression_values[len(previous_expression_values) - 1].as_matrix()


        # decide what to forget from previous state
        forget_matrix = forget_gate_layer(hidden_state_matrix, expr_for_prev_timepoint,combined_weight_matrix,bias_matrix)

        # pass the input thru input gate layer
        input_matrix = input_gate_layer(hidden_state_matrix,expr_for_prev_timepoint,combined_weight_matrix,bias_matrix)

        # combine the input with forget gate to get the actual input
        transformed_input_matrix = np.multiply(input_matrix,forget_matrix)

        # start looping over the genes
        for target_gene_index in range(0,gene_count):

            # get the target gene
            target_gene = trained_grn.genes[target_gene_index]

            # get the bias
            bias = trained_grn.bias[target_gene_index]

            # get the peak expression
            peak_expression = trained_grn.peak_expression_level[target_gene_index]

            # get the degradation constant
            degradation_constant = trained_grn.degradation_constant[target_gene_index]

            # get the regulators
            regulator_genes = trained_grn.get_regulators(target_gene)

            # loop over the regulators to calculate the expression from each regulator
            total_expression = 0
            for regulator_index in range(0,len(regulator_genes)):

                # get the regulator gene
                regulator_gene = regulator_genes[regulator_index]

                # get the original regulator index
                regulator_og_index = trained_grn.genes.index(regulator_gene)

                # get the previous expression values
                regulator_prev_expression_value = transformed_input_matrix[regulator_og_index]

                # get the weight
                weight = weight_matrix[target_gene_index,regulator_og_index]

                # calculate the expression
                expression = weight*regulator_prev_expression_value + bias

                total_expression = total_expression + expression

            # apply a sigmoid function to total expression
            target_gene_expression = peak_expression * sigmoid(total_expression) - degradation_constant

            # add the target gene expression to the matrix for current timepoint
            expr_for_curr_timepoint[target_gene_index] = target_gene_expression

        # add the current matrix to predicted expression matrix
        for gene_index in range(0,len(gene_labels)):
            predicted_expression_matrix.iat[gene_index,timepoint_index] = expr_for_curr_timepoint[gene_index]

        # save the current expression to be passed in next time step
        expr_for_prev_timepoint = expr_for_curr_timepoint

        # update the output that will be passed to new layer
        output_matrix = output_gate_layer(hidden_state_matrix,transformed_input_matrix,combined_weight_matrix,bias_matrix)

        hidden_state_matrix = output_matrix

    return predicted_expression_matrix


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


def forget_gate_layer(hidden_state_matrix, expr_for_curr_time_point,weight_matrix,bias_matrix):
    # expr_for_curr_time_point_list = expr_for_curr_time_point.aslist()
    result = (weight_matrix * expr_for_curr_time_point.T * hidden_state_matrix.T * random.uniform(0,1)) + bias_matrix.T
    v_sigmoid = np.vectorize(sigmoid)
    forget_matrix = v_sigmoid(result)
    return forget_matrix.T


def input_gate_layer(hidden_state_matrix,expr_for_curr_time_point,weight_matrix,bias_matrix):

    hidden_state_matrix_transposed = hidden_state_matrix.T
    expr_for_curr_time_point_transposed = expr_for_curr_time_point.T


    result = (weight_matrix * expr_for_curr_time_point_transposed * hidden_state_matrix_transposed * random.uniform(-1,1)) + bias_matrix
    v_tanh = np.vectorize(np.tanh)
    input_matrix = v_tanh(result)
    return input_matrix.T


def output_gate_layer(hidden_state_matrix,expr_for_curr_time_point,weight_matrix,bias_matrix):

    hidden_state_matrix_transposed = hidden_state_matrix.T
    expr_for_curr_time_point_transposed = expr_for_curr_time_point.T

    result = (weight_matrix * expr_for_curr_time_point_transposed * hidden_state_matrix_transposed * random.uniform(-1,1) ) + bias_matrix
    v_sigmoid = np.vectorize(sigmoid)
    result_matrix = v_sigmoid(result)

    v_tanh = np.vectorize(np.tanh)

    output_matrix = np.multiply(result_matrix,v_tanh(expr_for_curr_time_point_transposed))

    return output_matrix.T


def build_combined_weight_matrix(weight_matrix):
    result = np.zeros(len(weight_matrix))
    for index in range(0,len(result)):
        result[index] = weight_matrix[index].sum()
    return result

def extract_list_from_dict(dict):
    values = []

    for index,value in enumerate(dict.items()):
        if index != 0:
            values.append(value[0])

    return values


def calculate_mse(predicted_expression, testing_expression):
    predicted_matrix = predicted_expression.as_matrix()
    testing_matrix = testing_expression.as_matrix()

    mse = (((predicted_matrix - testing_matrix) ** 2).mean())

    return mse


class Grn:
    def __init__(self,genes,graph):
        self.genes = genes
        self.graph = graph
        self.bias = np.random.rand(len(self.genes))
        self.peak_expression_level = np.random.rand(len(self.genes))
        self.degradation_constant = np.random.rand(len(self.genes))

    def get_regulators(self,target_gene):
        pred = nx.predecessor(self.graph, target_gene, cutoff=1)
        pred = extract_list_from_dict(pred)
        return pred

    def relabel_nodes(self):
        mapping = dict(zip(self.graph.nodes(), self.genes))
        self.graph = nx.relabel_nodes(self.graph, mapping)


class GrnSpace:

    def __init__(self,gene_list,max_regulator_count,space_size = 10):
        self.gene_list = gene_list
        self.max_regulators_count = max_regulator_count
        self.space_size = space_size
        self.generated_count = 0

    def has_next(self):
        if self.generated_count < self.space_size:
            return True
        else:
            return False

    def get(self):

        graph = self._generate_graph()

        while not nx.is_directed_acyclic_graph(graph):
            print("is cyclic")
            graph = self._generate_graph()

        self.generated_count = self.generated_count + 1

        grn = Grn(self.gene_list,graph)
        return grn


    def _generate_graph(self):
        in_degree = []

        for gene in self.gene_list:
            in_degree.append(random.randint(0, 4))

        out_degree = in_degree[:]
        random.shuffle(out_degree)
        graph = nx.directed_configuration_model(in_degree, out_degree)
        mapping = dict(zip(graph.nodes(), self.gene_list))
        graph = nx.relabel_nodes(graph,mapping)
        return graph




